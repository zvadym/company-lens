from __future__ import annotations

from typing import Protocol

from sqlalchemy.orm import Session, sessionmaker

from company_lens.agent.schemas import AgentError, AgentErrorCategory, AgentErrorSeverity
from company_lens.financials.schemas import FinancialFactQuery, FinancialFactQueryResult
from company_lens.financials.service import FinancialFactQueryService
from company_lens.macro.schemas import FredSeriesQuery, FredSeriesResult
from company_lens.macro.service import FredQueryService
from company_lens.retrieval.adaptive import AdaptiveRetrievalService
from company_lens.retrieval.adaptive_schemas import (
    AdaptiveRetrievalRequest,
    AdaptiveRetrievalResponse,
    ResolvedQuery,
)
from company_lens.retrieval.embeddings import Embedder
from company_lens.retrieval.resolution import EntityResolver


class ResearchTools(Protocol):
    """Provider-neutral data port used by research graph nodes."""

    def resolve_entities(self, query: str) -> ResolvedQuery: ...

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
    ) -> None:
        self._session_factory = session_factory
        self._embedder = embedder

    def resolve_entities(self, query: str) -> ResolvedQuery:
        return self._call(lambda session: EntityResolver(session=session).resolve(query))

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
        return self._call(lambda session: FredQueryService(session=session).query(request))

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


class SessionOperation[ResultT](Protocol):
    def __call__(self, session: Session) -> ResultT: ...
