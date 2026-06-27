from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
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
        company, match_kind = _verified_sec_company(candidate, ticker_map)
        if company is not None:
            matches.append(
                public_company_resolution(
                    mention=candidate.mention,
                    ticker=company.ticker,
                    display_name=company.name,
                    match_kind=match_kind,
                )
            )
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


def _verified_sec_company(
    candidate: CompanyMentionCandidate,
    ticker_map: dict[str, SecCompany],
) -> tuple[SecCompany | None, str]:
    hinted_ticker = _normalized_ticker(candidate.ticker)
    if hinted_ticker is not None and (company := ticker_map.get(hinted_ticker)) is not None:
        return company, "sec_ticker_extracted"

    mention_ticker = _normalized_ticker(candidate.mention)
    if mention_ticker is not None and (company := ticker_map.get(mention_ticker)) is not None:
        return company, "sec_mention_ticker_extracted"

    cik = _normalized_cik(candidate.cik)
    if cik is not None:
        matches = sorted(
            (company for company in ticker_map.values() if company.cik.zfill(10) == cik),
            key=lambda item: item.ticker,
        )
        if matches:
            return matches[0], "sec_cik_extracted"

    for value, match_kind in (
        (candidate.legal_name, "sec_legal_name_extracted"),
        (candidate.mention, "sec_company_extracted"),
    ):
        company = _unique_company_name_match(value, ticker_map)
        if company is not None:
            return company, match_kind

    return None, "sec_unverified"


def _unique_company_name_match(
    value: str | None,
    ticker_map: dict[str, SecCompany],
) -> SecCompany | None:
    if value is None:
        return None
    normalized_value = _normalize(value)
    if not normalized_value:
        return None
    matches = {
        company.ticker.upper(): company
        for company in ticker_map.values()
        if _extracted_mention_matches_label(normalized_value, _company_label(company.name))
    }
    if len(matches) != 1:
        return None
    return next(iter(matches.values()))


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
