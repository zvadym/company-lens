from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from company_lens.agent.schemas import (
    AgentError,
    AgentErrorCategory,
    AgentErrorSeverity,
    CompanyMentionCandidate,
)
from company_lens.config import Settings
from company_lens.financials.schemas import FinancialFactQuery, FinancialFactQueryResult
from company_lens.financials.service import FinancialFactQueryService
from company_lens.ingestion.on_demand import (
    CompanyDataPreparationResult,
    OnDemandCompanyDataPreparer,
)
from company_lens.ingestion.sec_client import SecCompany
from company_lens.ingestion.sec_service import build_sec_client_from_settings
from company_lens.macro.client import FredClient
from company_lens.macro.schemas import FredSeriesQuery, FredSeriesResult
from company_lens.macro.service import FredIngestionService, FredQueryService
from company_lens.retrieval.adaptive import AdaptiveRetrievalService
from company_lens.retrieval.adaptive_schemas import (
    AdaptiveRetrievalRequest,
    AdaptiveRetrievalResponse,
    EntityCandidate,
    EntityResolution,
    ResolvedQuery,
)
from company_lens.retrieval.embeddings import Embedder
from company_lens.retrieval.resolution import EntityResolver, public_company_resolution


class ResearchTools(Protocol):
    """Provider-neutral data port used by research graph nodes."""

    def resolve_entities(self, query: str) -> ResolvedQuery: ...

    def resolve_non_company_entities(self, query: str) -> ResolvedQuery: ...

    def resolve_public_company_mentions(
        self,
        candidates: Sequence[CompanyMentionCandidate],
    ) -> tuple[EntityResolution, ...]: ...

    def prepare_companies(
        self,
        *,
        tickers: tuple[str, ...],
        company_ids: tuple[str, ...],
        index_name: str,
        index_version: str,
    ) -> CompanyDataPreparationResult: ...

    def retrieve_documents(
        self, request: AdaptiveRetrievalRequest
    ) -> AdaptiveRetrievalResponse: ...

    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult: ...

    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult: ...


class ResearchToolError(RuntimeError):
    def __init__(self, error: AgentError) -> None:
        self.error = error
        super().__init__(error.message)


class SqlResearchTools:
    """SQL-backed adapter that owns one short-lived session per call.

    LangGraph can execute independent branches concurrently. SQLAlchemy sessions are not
    shared across those branches; every method opens and closes its own session.
    """

    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        embedder: Embedder | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder
        self._settings = settings

    def resolve_entities(self, query: str) -> ResolvedQuery:
        resolved = self._resolve_entities(query)
        if resolved.company_ids or any(
            entity.kind == "public_company" for entity in resolved.entities
        ):
            return resolved
        public_entities = self._public_company_entities(query)
        if not public_entities:
            return resolved
        return resolved.model_copy(update={"entities": (*resolved.entities, *public_entities)})

    def resolve_non_company_entities(self, query: str) -> ResolvedQuery:
        return self._resolve_entities(query, include_companies=False)

    def resolve_public_company_mentions(
        self,
        candidates: Sequence[CompanyMentionCandidate],
    ) -> tuple[EntityResolution, ...]:
        cleaned = _clean_company_candidates(candidates)
        if not cleaned or self._settings is None or not self._settings.sec_user_agent:
            return ()
        try:
            with build_sec_client_from_settings(self._settings) as client:
                ticker_map = client.fetch_ticker_map()
        except Exception:
            return ()
        return _match_extracted_public_company_mentions(cleaned, ticker_map)

    def prepare_companies(
        self,
        *,
        tickers: tuple[str, ...],
        company_ids: tuple[str, ...],
        index_name: str,
        index_version: str,
    ) -> CompanyDataPreparationResult:
        if self._settings is None:
            return CompanyDataPreparationResult(
                status="disabled",
                requested_tickers=tuple(dict.fromkeys(ticker.upper() for ticker in tickers)),
                skipped_tickers=(),
                prepared_tickers=(),
            )
        try:
            parsed_company_ids = tuple(_parse_uuid(value) for value in company_ids)
            return OnDemandCompanyDataPreparer(
                settings=self._settings,
                session_factory=self._session_factory,
                embedder=self._embedder,
                index_name=index_name,
                index_version=index_version,
            ).prepare(tickers=tickers, company_ids=parsed_company_ids)
        except ResearchToolError:
            raise
        except Exception:
            raise ResearchToolError(
                AgentError(
                    category=AgentErrorCategory.TOOL,
                    severity=AgentErrorSeverity.RECOVERABLE,
                    code="company_data_preparation_failed",
                    message="Company report data could not be prepared on demand.",
                )
            ) from None

    def retrieve_documents(self, request: AdaptiveRetrievalRequest) -> AdaptiveRetrievalResponse:
        return self._call(
            lambda session: AdaptiveRetrievalService(
                session=session,
                embedder=self._embedder,
            ).retrieve(request)
        )

    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        return self._call(lambda session: FinancialFactQueryService(session=session).query(request))

    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        try:
            with self._session_factory() as session:
                result = FredQueryService(session=session).query(request)
                missing_series = _missing_fred_series(result)
                if (
                    not missing_series
                    or self._settings is None
                    or self._settings.fred_api_key is None
                ):
                    return result
                try:
                    with FredClient(
                        api_key=self._settings.fred_api_key.get_secret_value(),
                        base_url=self._settings.fred_base_url,
                        timeout_seconds=self._settings.fred_request_timeout_seconds,
                        retry_attempts=self._settings.fred_retry_attempts,
                    ) as client:
                        FredIngestionService(session=session, client=client).ingest(
                            missing_series,
                            observation_start=request.observation_start,
                            observation_end=request.observation_end,
                        )
                    return FredQueryService(session=session).query(request)
                except Exception:
                    return result.model_copy(
                        update={
                            "warnings": (
                                *result.warnings,
                                "on_demand_fred_ingestion_failed:" + ",".join(missing_series),
                            )
                        }
                    )
        except ResearchToolError:
            raise
        except (ValueError, TypeError):
            raise ResearchToolError(
                AgentError(
                    category=AgentErrorCategory.VALIDATION,
                    severity=AgentErrorSeverity.TERMINAL,
                    code="tool_invalid_request",
                    message="A research tool rejected its typed request.",
                )
            ) from None
        except Exception:
            raise ResearchToolError(
                AgentError(
                    category=AgentErrorCategory.TOOL,
                    severity=AgentErrorSeverity.RECOVERABLE,
                    code="tool_execution_failed",
                    message="A research data operation failed.",
                )
            ) from None

    def _resolve_entities(self, query: str, *, include_companies: bool = True) -> ResolvedQuery:
        try:
            with self._session_factory.begin() as session:
                return EntityResolver(session=session).resolve(
                    query,
                    include_companies=include_companies,
                )
        except ResearchToolError:
            raise
        except (ValueError, TypeError):
            raise ResearchToolError(
                AgentError(
                    category=AgentErrorCategory.VALIDATION,
                    severity=AgentErrorSeverity.TERMINAL,
                    code="tool_invalid_request",
                    message="A research tool rejected its typed request.",
                )
            ) from None
        except Exception:
            raise ResearchToolError(
                AgentError(
                    category=AgentErrorCategory.TOOL,
                    severity=AgentErrorSeverity.RECOVERABLE,
                    code="tool_execution_failed",
                    message="A research data operation failed.",
                )
            ) from None

    def _call[ResultT](self, operation: SessionOperation[ResultT]) -> ResultT:
        try:
            with self._session_factory() as session:
                return operation(session)
        except ResearchToolError:
            raise
        except (ValueError, TypeError):
            raise ResearchToolError(
                AgentError(
                    category=AgentErrorCategory.VALIDATION,
                    severity=AgentErrorSeverity.TERMINAL,
                    code="tool_invalid_request",
                    message="A research tool rejected its typed request.",
                )
            ) from None
        except Exception:
            raise ResearchToolError(
                AgentError(
                    category=AgentErrorCategory.TOOL,
                    severity=AgentErrorSeverity.RECOVERABLE,
                    code="tool_execution_failed",
                    message="A research data operation failed.",
                )
            ) from None

    def _public_company_entities(self, query: str) -> tuple[EntityResolution, ...]:
        if self._settings is None or not self._settings.sec_user_agent:
            return ()
        try:
            with build_sec_client_from_settings(self._settings) as client:
                ticker_map = client.fetch_ticker_map()
        except Exception:
            return ()
        return _match_public_companies(query, ticker_map)


class SessionOperation[ResultT](Protocol):
    def __call__(self, session: Session) -> ResultT: ...


def _match_public_companies(
    query: str,
    ticker_map: dict[str, SecCompany],
) -> tuple[EntityResolution, ...]:
    matches: list[tuple[str, SecCompany, str]] = []
    seen: set[str] = set()
    for ticker, company in ticker_map.items():
        if _ticker_mentioned(query, ticker):
            matches.append((ticker, company, "sec_ticker"))
            seen.add(ticker)
    normalized_query = f" {_normalize(query)} "
    for ticker, company in ticker_map.items():
        if ticker in seen:
            continue
        label = _company_label(company.name)
        if len(label) < 4:
            continue
        if re.search(rf"(?<!\w){re.escape(label)}(?!\w)", normalized_query):
            matches.append((label, company, "sec_company_name"))
            seen.add(ticker)
    return tuple(
        public_company_resolution(
            mention=mention,
            ticker=company.ticker,
            display_name=company.name,
            match_kind=match_kind,
        )
        for mention, company, match_kind in matches[:5]
    )


def _match_extracted_public_company_mentions(
    candidates: Sequence[CompanyMentionCandidate],
    ticker_map: dict[str, SecCompany],
) -> tuple[EntityResolution, ...]:
    matches: list[EntityResolution] = []
    for candidate in candidates:
        entity = _sec_company_resolution(candidate, ticker_map)
        if entity is not None:
            matches.append(entity)
    return _dedupe_public_company_entities(tuple(matches))


def _clean_company_candidates(
    candidates: Sequence[CompanyMentionCandidate],
) -> tuple[CompanyMentionCandidate, ...]:
    unique: dict[tuple[str, str | None, str | None, str | None], CompanyMentionCandidate] = {}
    for candidate in candidates:
        key = (
            candidate.mention.casefold(),
            candidate.ticker.casefold() if candidate.ticker else None,
            candidate.cik,
            candidate.legal_name.casefold() if candidate.legal_name else None,
        )
        unique.setdefault(key, candidate)
    return tuple(unique.values())


@dataclass(frozen=True)
class _RankedSecCompany:
    company: SecCompany
    score: int
    match_kind: str


_CLEAR_SEC_MATCH_MARGIN = 15
_COMMON_NON_COMPANY_TERMS = {
    "area",
    "bar",
    "bars",
    "cash",
    "chart",
    "charts",
    "graph",
    "graphs",
    "growth",
    "income",
    "line",
    "lines",
    "margin",
    "plot",
    "plots",
    "profit",
    "rate",
    "rates",
    "revenue",
    "sales",
    "scatter",
    "table",
}


def _sec_company_resolution(
    candidate: CompanyMentionCandidate,
    ticker_map: dict[str, SecCompany],
) -> EntityResolution | None:
    clear_mention_match = _clear_sec_mention_name_resolution(candidate, ticker_map)
    if clear_mention_match is not None:
        return clear_mention_match

    ambiguous_name_matches = _ambiguous_sec_name_matches(candidate, ticker_map)
    if ambiguous_name_matches:
        return _ambiguous_sec_company_resolution(candidate.mention, ambiguous_name_matches)

    ranked = _rank_sec_company_candidates(candidate, ticker_map)
    if not ranked:
        return None

    top = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    if runner_up is None or top.score >= runner_up.score + _CLEAR_SEC_MATCH_MARGIN:
        return public_company_resolution(
            mention=candidate.mention,
            ticker=top.company.ticker,
            display_name=top.company.name,
            match_kind=top.match_kind,
        )

    return _ambiguous_sec_company_resolution(candidate.mention, ranked)


def _clear_sec_mention_name_resolution(
    candidate: CompanyMentionCandidate,
    ticker_map: dict[str, SecCompany],
) -> EntityResolution | None:
    if candidate.cik or (candidate.legal_name and not candidate.ticker):
        return None
    if _mention_is_explicit_ticker(candidate.mention, ticker_map):
        return None
    if _normalize(candidate.mention) in _COMMON_NON_COMPANY_TERMS or _blocks_name_match(
        candidate, candidate.mention
    ):
        return None
    ranked = _rank_sec_name_candidates(
        candidate.mention,
        ticker_map,
        exact_score=100,
        prefix_score=80,
        match_kind="sec_company_extracted",
    )
    if not ranked:
        return None
    top = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    # A clear extracted name should beat a contradictory LLM ticker hint.
    if top.score < 100 or (
        runner_up is not None and top.score < runner_up.score + _CLEAR_SEC_MATCH_MARGIN
    ):
        return None
    return public_company_resolution(
        mention=candidate.mention,
        ticker=top.company.ticker,
        display_name=top.company.name,
        match_kind=top.match_kind,
    )


def _ambiguous_sec_company_resolution(
    mention: str,
    ranked: tuple[_RankedSecCompany, ...],
) -> EntityResolution:
    candidates = _unique_ambiguous_sec_matches(ranked)
    return EntityResolution(
        kind="public_company",
        mention=mention,
        status="ambiguous",
        candidates=tuple(
            EntityCandidate(
                canonical_value=match.company.ticker.upper(),
                display_value=match.company.name,
                match_kind=match.match_kind,
            )
            for match in candidates[:5]
        ),
    )


def _unique_ambiguous_sec_matches(
    ranked: tuple[_RankedSecCompany, ...],
) -> tuple[_RankedSecCompany, ...]:
    unique: list[_RankedSecCompany] = []
    seen_labels: set[str] = set()
    for match in ranked:
        label = _company_label(match.company.name)
        if label in seen_labels:
            continue
        seen_labels.add(label)
        unique.append(match)
    return tuple(unique) if len(unique) >= 2 else ranked


def _ambiguous_sec_name_matches(
    candidate: CompanyMentionCandidate,
    ticker_map: dict[str, SecCompany],
) -> tuple[_RankedSecCompany, ...]:
    if _mention_is_explicit_ticker(candidate.mention, ticker_map):
        return ()
    if _normalize(candidate.mention) in _COMMON_NON_COMPANY_TERMS or _blocks_name_match(
        candidate, candidate.mention
    ):
        return ()
    ranked = _rank_sec_name_candidates(
        candidate.mention,
        ticker_map,
        exact_score=75,
        prefix_score=60,
        match_kind="sec_company_extracted",
    )
    if len(ranked) < 2:
        return ()
    top, runner_up = ranked[0], ranked[1]
    if top.score >= runner_up.score + _CLEAR_SEC_MATCH_MARGIN:
        return ()
    return ranked


def _rank_sec_company_candidates(
    candidate: CompanyMentionCandidate,
    ticker_map: dict[str, SecCompany],
) -> tuple[_RankedSecCompany, ...]:
    ranked: dict[str, _RankedSecCompany] = {}

    def add(company: SecCompany | None, score: int, match_kind: str) -> None:
        if company is None:
            return
        key = company.ticker.upper()
        existing = ranked.get(key)
        match = _RankedSecCompany(company=company, score=score, match_kind=match_kind)
        if existing is None or match.score > existing.score:
            ranked[key] = match

    hinted_ticker = _normalized_ticker(candidate.ticker)
    if not _blocks_plain_ticker_match(candidate):
        add(
            ticker_map.get(hinted_ticker) if hinted_ticker is not None else None,
            100,
            "sec_ticker_extracted",
        )

    mention_ticker = _normalized_ticker(candidate.mention)
    if not _blocks_plain_ticker_match(candidate):
        add(
            ticker_map.get(mention_ticker) if mention_ticker is not None else None,
            95 if candidate.mention.strip().startswith("$") else 90,
            "sec_mention_ticker_extracted",
        )

    cik = _normalized_cik(candidate.cik)
    if cik is not None:
        matches = sorted(
            (company for company in ticker_map.values() if company.cik.zfill(10) == cik),
            key=lambda item: item.ticker,
        )
        for company in matches:
            add(company, 100, "sec_cik_extracted")

    for value, exact_score, prefix_score, match_kind in (
        (candidate.legal_name, 85, 70, "sec_legal_name_extracted"),
        (candidate.mention, 75, 60, "sec_company_extracted"),
    ):
        if value is None or _blocks_name_match(candidate, value):
            continue
        for match in _rank_sec_name_candidates(
            value,
            ticker_map,
            exact_score=exact_score,
            prefix_score=prefix_score,
            match_kind=match_kind,
        ):
            add(match.company, match.score, match.match_kind)

    return tuple(sorted(ranked.values(), key=lambda item: (-item.score, item.company.ticker)))


def _rank_sec_name_candidates(
    value: str,
    ticker_map: dict[str, SecCompany],
    *,
    exact_score: int,
    prefix_score: int,
    match_kind: str,
) -> tuple[_RankedSecCompany, ...]:
    ranked: list[_RankedSecCompany] = []
    for company in ticker_map.values():
        score = _sec_name_match_score(value, company, exact_score, prefix_score)
        if score is not None:
            ranked.append(_RankedSecCompany(company=company, score=score, match_kind=match_kind))
    return tuple(
        sorted(
            ranked,
            key=lambda item: (
                -item.score,
                _company_label(item.company.name),
                item.company.ticker,
            ),
        )
    )


def _sec_name_match_score(
    value: str,
    company: SecCompany,
    exact_score: int,
    prefix_score: int,
) -> int | None:
    normalized_value = _company_label(value)
    label = _company_label(company.name)
    if not normalized_value or not label:
        return None
    if normalized_value == label:
        return exact_score
    if _extracted_mention_matches_label(normalized_value, label):
        return prefix_score
    return None


def _blocks_plain_ticker_match(candidate: CompanyMentionCandidate) -> bool:
    if candidate.mention.strip().startswith("$"):
        return False
    if candidate.cik or candidate.legal_name:
        return False
    normalized = _normalize(candidate.mention)
    return normalized in _COMMON_NON_COMPANY_TERMS


def _mention_is_explicit_ticker(
    mention: str,
    ticker_map: dict[str, SecCompany],
) -> bool:
    stripped = mention.strip()
    ticker = _normalized_ticker(stripped)
    if ticker is None or ticker not in ticker_map:
        return False
    if stripped.startswith("$"):
        return True
    return len(ticker) > 1 and _normalize(stripped) not in _COMMON_NON_COMPANY_TERMS


def _blocks_name_match(candidate: CompanyMentionCandidate, value: str) -> bool:
    if candidate.cik or candidate.legal_name:
        return False
    normalized_value = _normalize(value)
    return normalized_value in _COMMON_NON_COMPANY_TERMS


def _normalized_ticker(value: str | None) -> str | None:
    if value is None:
        return None
    ticker = value.strip().upper().removeprefix("$")
    if not ticker or " " in ticker:
        return None
    return ticker


def _normalized_cik(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped.isdigit() or len(stripped) > 10:
        return None
    return stripped.zfill(10)


def _extracted_mention_matches_label(mention: str, label: str) -> bool:
    if not label or len(mention) < 2:
        return False
    if mention == label:
        return True
    if len(mention) >= 4 and label.startswith(f"{mention} "):
        return True
    label_tokens = label.split()
    mention_tokens = mention.split()
    return len(mention_tokens) > 1 and label_tokens[: len(mention_tokens)] == mention_tokens


def _dedupe_public_company_entities(
    entities: Sequence[EntityResolution],
) -> tuple[EntityResolution, ...]:
    unique: dict[tuple[str, str], EntityResolution] = {}
    for entity in entities:
        key = (
            entity.kind,
            entity.canonical_value
            or (entity.candidates[0].canonical_value if entity.candidates else entity.mention),
        )
        unique.setdefault(key, entity)
    return tuple(unique.values())


def _missing_fred_series(result: FredSeriesResult) -> tuple[str, ...]:
    missing: list[str] = []
    for warning in result.warnings:
        if not warning.startswith("series_not_cached:"):
            continue
        missing.extend(
            series_id.strip().upper()
            for series_id in warning.removeprefix("series_not_cached:").split(",")
            if series_id.strip()
        )
    return tuple(dict.fromkeys(missing))


def _ticker_mentioned(query: str, ticker: str) -> bool:
    if len(ticker) == 1:
        return bool(re.search(rf"(?<![A-Za-z0-9])\${re.escape(ticker)}(?![A-Za-z0-9])", query))
    return bool(re.search(rf"(?<![A-Za-z0-9])\$?{re.escape(ticker)}(?![A-Za-z0-9])", query))


def _company_label(name: str) -> str:
    label = _normalize(name)
    suffixes = {
        "inc",
        "incorporated",
        "corp",
        "corporation",
        "co",
        "company",
        "ltd",
        "limited",
        "plc",
        "class a",
        "class b",
        "common stock",
    }
    changed = True
    while changed:
        changed = False
        for suffix in suffixes:
            if label.endswith(f" {suffix}"):
                label = label[: -(len(suffix) + 1)].strip()
                changed = True
    return label


def _normalize(value: str) -> str:
    return " ".join(re.sub(r"[^\w]+", " ", value.casefold()).split())


def _parse_uuid(value: str) -> uuid.UUID:
    return uuid.UUID(value)
