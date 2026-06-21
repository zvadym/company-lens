from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from typing import cast

import pytest
from pydantic import BaseModel
from sqlalchemy import Table, create_engine

from company_lens.agent.model import (
    ModelMessage,
    ModelPurpose,
    StructuredModelResult,
    TextModelResult,
)
from company_lens.agent.persistence import (
    PersistentResearchAgent,
    ResearchSessionManager,
    ResearchSessionRepository,
    postgres_checkpointer,
)
from company_lens.agent.schemas import (
    AgentRunStatus,
    ModelExecutionPlan,
    QuestionAnalysis,
    ResearchRoute,
)
from company_lens.agent.workflow import ResearchAgentRuntime
from company_lens.db.models import ResearchSession
from company_lens.db.session import build_session_factory
from company_lens.financials.schemas import FinancialFactQuery, FinancialFactQueryResult
from company_lens.macro.schemas import FredSeriesQuery, FredSeriesResult
from company_lens.retrieval.adaptive_schemas import (
    AdaptiveRetrievalRequest,
    AdaptiveRetrievalResponse,
    ResolvedQuery,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("COMPANY_LENS_TEST_DATABASE_URL"),
    reason="COMPANY_LENS_TEST_DATABASE_URL is not set.",
)


class UnsupportedModel:
    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        output: BaseModel = (
            QuestionAnalysis(
                normalized_question="Unsupported request",
                route=ResearchRoute.UNSUPPORTED,
                reason_codes=("outside_research_scope",),
            )
            if output_type is QuestionAnalysis
            else ModelExecutionPlan(route=ResearchRoute.UNSUPPORTED)
        )
        return StructuredModelResult[OutputT](
            model="fake",
            response_id=str(uuid.uuid4()),
            output=cast(OutputT, output),
        )

    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult:
        raise AssertionError("Unsupported route must not generate an answer.")


class NoDataTools:
    def resolve_entities(self, query: str) -> ResolvedQuery:
        return ResolvedQuery(query=query)

    def retrieve_documents(self, request: AdaptiveRetrievalRequest) -> AdaptiveRetrievalResponse:
        raise AssertionError

    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        raise AssertionError

    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        raise AssertionError


def test_postgres_checkpointer_survives_agent_reconstruction_and_clear() -> None:
    database_url = os.environ["COMPANY_LENS_TEST_DATABASE_URL"]
    engine = create_engine(database_url)
    table = cast(Table, ResearchSession.__table__)
    ResearchSession.metadata.create_all(engine, tables=[table])
    repository = ResearchSessionRepository(build_session_factory(database_url))
    session_id = f"postgres-{uuid.uuid4()}"
    runtime = ResearchAgentRuntime(UnsupportedModel(), NoDataTools())

    with postgres_checkpointer(database_url, setup=True) as checkpointer:
        first_agent = PersistentResearchAgent(
            runtime=runtime,
            checkpointer=checkpointer,
            session_repository=repository,
        )
        result = first_agent.run("Write a poem", session_id=session_id)
        assert result["status"] is AgentRunStatus.ABSTAINED

        reconstructed = PersistentResearchAgent(
            runtime=runtime,
            checkpointer=checkpointer,
            session_repository=repository,
        )
        snapshot = reconstructed.inspect_session(session_id)
        assert snapshot is not None
        assert snapshot.state["run_id"] == result["run_id"]
        manager = ResearchSessionManager(
            checkpointer=checkpointer,
            session_repository=repository,
        )
        managed_snapshot = manager.inspect_session(session_id)
        assert managed_snapshot is not None
        assert managed_snapshot.state["run_id"] == result["run_id"]
        assert manager.clear_session(session_id) is True
        assert manager.inspect_session(session_id) is None
