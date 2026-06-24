from __future__ import annotations

import re
import uuid
from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from company_lens.agent.schemas import AgentError, AgentErrorCategory, AgentErrorSeverity
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
        resolved = self._call(lambda session: EntityResolver(session=session).resolve(query))
        if resolved.company_ids or any(
            entity.kind == "public_company" for entity in resolved.entities
        ):
            return resolved
        public_entities = self._public_company_entities(query)
        if not public_entities:
            return resolved
        return resolved.model_copy(update={"entities": (*resolved.entities, *public_entities)})

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
