from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import cast

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import BaseModel
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from company_lens.agent.model import (
    ModelMessage,
    ModelPurpose,
    StructuredModelResult,
    TextModelResult,
)
from company_lens.agent.persistence import (
    PersistentResearchAgent,
    ResearchSessionError,
    ResearchSessionRepository,
    SessionErrorCode,
    checkpoint_serializer,
)
from company_lens.agent.schemas import (
    AgentCapability,
    AgentRunStatus,
    AgentState,
    ModelExecutionBranch,
    ModelExecutionPlan,
    QuestionAnalysis,
    ResearchRoute,
    SessionMemory,
)
from company_lens.agent.workflow import ResearchAgentRuntime, build_research_graph
from company_lens.db.models import ResearchSession
from company_lens.financials.schemas import (
    FinancialFactObservation,
    FinancialFactQuery,
    FinancialFactQueryResult,
)
from company_lens.macro.schemas import FredSeriesQuery, FredSeriesResult
from company_lens.retrieval.adaptive_schemas import (
    AdaptiveRetrievalRequest,
    AdaptiveRetrievalResponse,
    ResolvedQuery,
)

COMPANY_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
FACT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")


class QueueModelProvider:
    def __init__(
        self,
        *,
        analyses: Sequence[QuestionAnalysis],
        plans: Sequence[ModelExecutionPlan],
        texts: Sequence[str],
    ) -> None:
        self.analyses = list(analyses)
        self.plans = list(plans)
        self.texts = list(texts)

    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        output: BaseModel
        if output_type is QuestionAnalysis:
            output = self.analyses.pop(0)
        elif output_type is ModelExecutionPlan:
            output = self.plans.pop(0)
        else:
            raise AssertionError(f"Unexpected output type: {output_type}")
        return StructuredModelResult[OutputT](
            model="fake-planning",
            response_id=str(uuid.uuid4()),
            output=cast(OutputT, output),
        )

    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult:
        return TextModelResult(
            model="fake-answer",
            response_id=str(uuid.uuid4()),
            text=self.texts.pop(0),
        )


class CountingTools:
    def __init__(self) -> None:
        self.calls: defaultdict[str, int] = defaultdict(int)

    def resolve_entities(self, query: str) -> ResolvedQuery:
        self.calls["resolve"] += 1
        if "what about" not in query.lower() and "that result" not in query.lower():
            return ResolvedQuery(
                query=query,
                company_ids=(COMPANY_ID,),
                metrics=("revenue",),
                fiscal_years=(2025,),
            )
        return ResolvedQuery(query=query, fiscal_years=(2024,))

    def retrieve_documents(self, request: AdaptiveRetrievalRequest) -> AdaptiveRetrievalResponse:
        raise AssertionError("Retrieval was not expected.")

    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        year = request.fiscal_years[0] if request.fiscal_years else 2025
        return FinancialFactQueryResult(
            query=request,
            observations=(_fact(year),),
            available_units=("USD",),
        )

    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        raise AssertionError("Macro query was not expected.")


@pytest.fixture
def repository() -> ResearchSessionRepository:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    table = cast(Table, ResearchSession.__table__)
    ResearchSession.metadata.create_all(engine, tables=[table])
    return ResearchSessionRepository(sessionmaker(bind=engine, expire_on_commit=False))


def test_two_turns_preserve_messages_reset_run_state_and_reuse_exact_result(
    repository: ResearchSessionRepository,
) -> None:
    model = QueueModelProvider(
        analyses=(_analysis(False), _analysis(True)),
        plans=(_plan(2025), _plan(2025)),
        texts=(_answer(2025), _answer(2025)),
    )
    tools = CountingTools()
    checkpointer = InMemorySaver(serde=checkpoint_serializer())
    agent = _agent(model, tools, repository, checkpointer)

    first = agent.run("What was Cloudflare revenue?", session_id="conversation-1")
    second = agent.run("And what about that result?", session_id="conversation-1")

    assert first["status"] is AgentRunStatus.COMPLETED
    assert second["status"] is AgentRunStatus.COMPLETED
    assert tools.calls["financial"] == 1
    assert second["tool_calls_used"] == 0
    assert len(second["financial_results"]) == 1
    assert [message.role for message in second["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert second["resolved_query"] is not None
    assert second["resolved_query"].company_ids == (COMPANY_ID,)
    assert second["resolved_query"].fiscal_years == (2024,)
    inspected = agent.inspect_session("conversation-1")
    assert inspected is not None
    assert inspected.metadata.turn_count == 2
    assert inspected.pending_nodes == ()


def test_changed_typed_request_does_not_reuse_cached_result(
    repository: ResearchSessionRepository,
) -> None:
    model = QueueModelProvider(
        analyses=(_analysis(False), _analysis(True)),
        plans=(_plan(2025), _plan(2024)),
        texts=(_answer(2025), _answer(2024)),
    )
    tools = CountingTools()
    agent = _agent(model, tools, repository, InMemorySaver(serde=checkpoint_serializer()))

    agent.run("Revenue in 2025?", session_id="conversation-2")
    result = agent.run("What about 2024?", session_id="conversation-2")

    assert result["status"] is AgentRunStatus.COMPLETED
    assert tools.calls["financial"] == 2
    assert result["tool_calls_used"] == 1


def test_pending_checkpoint_requires_resume_and_does_not_repeat_tool_call(
    repository: ResearchSessionRepository,
) -> None:
    model = QueueModelProvider(
        analyses=(_analysis(False),),
        plans=(_plan(2025),),
        texts=(_answer(2025),),
    )
    tools = CountingTools()
    checkpointer = InMemorySaver(serde=checkpoint_serializer())
    runtime = ResearchAgentRuntime(model, tools)
    graph = build_research_graph(checkpointer, interrupt_before=["generate_answer"])
    agent = PersistentResearchAgent(
        runtime=runtime,
        checkpointer=checkpointer,
        session_repository=repository,
        graph=graph,
    )

    interrupted = agent.run("Revenue in 2025?", session_id="conversation-resume")
    inspected = agent.inspect_session("conversation-resume")

    assert interrupted["final_answer"] is None
    assert inspected is not None
    assert inspected.pending_nodes == ("generate_answer",)
    assert inspected.resumable is True
    with pytest.raises(ResearchSessionError) as captured:
        agent.run("A new question", session_id="conversation-resume")
    assert captured.value.code is SessionErrorCode.RESUME_REQUIRED

    resumed = agent.resume("conversation-resume")

    assert resumed["status"] is AgentRunStatus.COMPLETED
    assert tools.calls["financial"] == 1
    with pytest.raises(ResearchSessionError) as completed:
        agent.resume("conversation-resume")
    assert completed.value.code is SessionErrorCode.NOT_RESUMABLE


def test_clear_is_hard_delete_and_active_lease_is_protected(
    repository: ResearchSessionRepository,
) -> None:
    model = QueueModelProvider(
        analyses=(_analysis(False),),
        plans=(_plan(2025),),
        texts=(_answer(2025),),
    )
    agent = _agent(
        model,
        CountingTools(),
        repository,
        InMemorySaver(serde=checkpoint_serializer()),
    )
    agent.run("Revenue?", session_id="conversation-clear")
    metadata = repository.get("conversation-clear")
    assert metadata is not None
    active_id = uuid.uuid4()
    now = datetime.now(UTC)
    repository.acquire(
        "conversation-clear",
        active_id,
        now=now,
        lease_expires_at=now + timedelta(minutes=5),
    )

    with pytest.raises(ResearchSessionError) as busy:
        agent.clear_session("conversation-clear")
    assert busy.value.code is SessionErrorCode.BUSY

    repository.release(
        "conversation-clear",
        active_id,
        now=now,
        expires_at=now + timedelta(hours=24),
        increment_turn=False,
    )
    assert agent.clear_session("conversation-clear") is True
    assert agent.inspect_session("conversation-clear") is None
    assert agent.clear_session("conversation-clear") is False


def test_expiry_cleanup_is_sliding_and_idempotent(
    repository: ResearchSessionRepository,
) -> None:
    model = QueueModelProvider(
        analyses=(_analysis(False), _analysis(False)),
        plans=(_plan(2025), _plan(2025)),
        texts=(_answer(2025), _answer(2025)),
    )
    checkpointer = InMemorySaver(serde=checkpoint_serializer())
    agent = PersistentResearchAgent(
        runtime=ResearchAgentRuntime(model, CountingTools()),
        checkpointer=checkpointer,
        session_repository=repository,
        ttl=timedelta(seconds=1),
    )
    before = datetime.now(UTC)

    agent.run("Revenue?", session_id="conversation-expiry")
    metadata = repository.get("conversation-expiry")

    assert metadata is not None
    assert metadata.expires_at > before
    assert agent.expire_sessions(now=metadata.expires_at + timedelta(seconds=1)) == 1
    assert agent.expire_sessions(now=metadata.expires_at + timedelta(seconds=1)) == 0
    assert agent.inspect_session("conversation-expiry") is None

    fresh_agent = _agent(model, CountingTools(), repository, checkpointer)
    fresh = fresh_agent.run("A fresh session", session_id="conversation-expiry")
    refreshed = fresh_agent.inspect_session("conversation-expiry")
    assert len(fresh["messages"]) == 2
    assert refreshed is not None
    assert refreshed.metadata.turn_count == 1


def test_session_ids_are_checkpoint_isolation_boundaries(
    repository: ResearchSessionRepository,
) -> None:
    model = QueueModelProvider(
        analyses=(_analysis(False), _analysis(False)),
        plans=(_plan(2025), _plan(2025)),
        texts=(_answer(2025), _answer(2025)),
    )
    agent = _agent(
        model,
        CountingTools(),
        repository,
        InMemorySaver(serde=checkpoint_serializer()),
    )

    first = agent.run("First company question", session_id="isolated-a")
    second = agent.run("Second company question", session_id="isolated-b")

    assert [message.content for message in first["messages"] if message.role == "user"] == [
        "First company question"
    ]
    assert [message.content for message in second["messages"] if message.role == "user"] == [
        "Second company question"
    ]


def test_session_message_limit_is_enforced_after_checkpoint_round_trips(
    repository: ResearchSessionRepository,
) -> None:
    turns = 4
    years = tuple(2022 + index for index in range(turns))
    model = QueueModelProvider(
        analyses=tuple(_analysis(index > 0) for index in range(turns)),
        plans=tuple(_plan(year) for year in years),
        texts=tuple(_answer(year) for year in years),
    )
    runtime = ResearchAgentRuntime(
        model,
        CountingTools(),
        max_session_messages=4,
        max_cached_source_results=2,
    )
    agent = PersistentResearchAgent(
        runtime=runtime,
        checkpointer=InMemorySaver(serde=checkpoint_serializer()),
        session_repository=repository,
    )

    result: AgentState
    for index in range(turns):
        result = agent.run(f"Question {index}", session_id="conversation-limit")

    assert len(result["messages"]) <= 4
    memory = result["session_memory"]
    assert isinstance(memory, SessionMemory)
    assert len(memory.cached_source_results) <= 2


def _agent(
    model: QueueModelProvider,
    tools: CountingTools,
    repository: ResearchSessionRepository,
    checkpointer: InMemorySaver,
) -> PersistentResearchAgent:
    return PersistentResearchAgent(
        runtime=ResearchAgentRuntime(model, tools),
        checkpointer=checkpointer,
        session_repository=repository,
    )


def _analysis(follow_up: bool) -> QuestionAnalysis:
    return QuestionAnalysis(
        normalized_question="Cloudflare revenue",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
        is_follow_up=follow_up,
    )


def _plan(year: int) -> ModelExecutionPlan:
    return ModelExecutionPlan(
        route=ResearchRoute.STRUCTURED_ONLY,
        branches=(
            ModelExecutionBranch(
                kind="query_financial_facts",
                branch_id="financial",
                financial_request=FinancialFactQuery(
                    company_ids=(COMPANY_ID,),
                    metrics=("revenue",),
                    fiscal_years=(year,),
                ),
            ),
        ),
    )


def _answer(year: int) -> str:
    return f"Revenue for {year} is 100 USD [financial_fact:22222222-2222-2222-2222-222222222222]."


def _fact(year: int) -> FinancialFactObservation:
    return FinancialFactObservation(
        id=FACT_ID,
        company_id=COMPANY_ID,
        company_name="Cloudflare",
        ticker="NET",
        metric="revenue",
        value=Decimal("100"),
        unit="USD",
        period_start=date(year, 1, 1),
        period_end=date(year, 12, 31),
        period_type="annual",
        fiscal_year=year,
        fiscal_period="FY",
        form="10-K",
        filed_date=date(year, 12, 31),
        accession_number=f"{year}-fixture",
        taxonomy="us-gaap",
        concept="Revenue",
        frame=None,
        is_amendment=False,
        has_conflict=False,
        mapping_version="v1",
        source_url=f"https://sec.example/{year}",
    )
