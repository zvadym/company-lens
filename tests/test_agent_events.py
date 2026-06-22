from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from company_lens.agent.events import (
    project_agent_transition,
    task_finished_event,
    task_started_event,
)
from company_lens.agent.schemas import (
    AgentCapability,
    AgentRunStatus,
    AgentState,
    BranchOutcome,
    BranchStatus,
    CalculationBranch,
    CalculationBranchResult,
    ChartBranch,
    DocumentRetrievalBranch,
    ExecutionPlan,
    ExecutionPolicy,
    FinancialBranchResult,
    FinancialFactsBranch,
    MacroBranchResult,
    MacroSeriesBranch,
    QuestionAnalysis,
    ResearchRoute,
    RetrievalBranchResult,
    TrajectoryEvent,
    TrajectoryStatus,
)
from company_lens.analytics.schemas import (
    CalculationPoint,
    CalculationResult,
    ChartPoint,
    ChartSeries,
    ChartSpecification,
    NumericObservation,
)
from company_lens.evidence.schemas import (
    AnswerValidation,
    ClaimRecord,
    ClaimValidation,
    SemanticSupportResult,
    SemanticSupportStatus,
)
from company_lens.financials.schemas import FinancialFactQuery, FinancialFactQueryResult
from company_lens.macro.schemas import FredSeriesQuery, FredSeriesResult
from company_lens.research.schemas import ResearchEventEnvelope
from company_lens.retrieval.adaptive_schemas import (
    AdaptiveRetrievalRequest,
    AdaptiveRetrievalResponse,
    ContextEvidence,
    ResolvedQuery,
    RetrievalPlan,
    RetrievalTrace,
)


def test_projector_emits_educational_summaries_without_private_state() -> None:
    company_id = uuid.uuid4()
    retrieval = DocumentRetrievalBranch(
        branch_id="documents",
        request=AdaptiveRetrievalRequest(query="Public retrieval query"),
    )
    financial = FinancialFactsBranch(
        branch_id="facts",
        request=FinancialFactQuery(company_ids=(company_id,), metrics=("revenue",)),
    )
    macro = MacroSeriesBranch(
        branch_id="macro",
        request=FredSeriesQuery(series_ids=("FEDFUNDS",)),
    )
    calculation = CalculationBranch(
        branch_id="growth",
        depends_on=("facts",),
        operation="year_over_year_growth",
        input_refs=("facts",),
    )
    chart = ChartBranch(
        branch_id="chart",
        depends_on=("growth",),
        chart_type="line",
        dataset_ref="growth",
        title="Revenue growth",
    )
    plan = ExecutionPlan(
        route=ResearchRoute.HYBRID,
        branches=(retrieval, financial, macro, calculation, chart),
        reason_codes=("hybrid_sources",),
    )
    initial = _state()
    planned: AgentState = {
        **initial,
        "analysis": QuestionAnalysis(
            normalized_question="Compare revenue and rates",
            route=ResearchRoute.HYBRID,
            required_capabilities=(
                AgentCapability.DOCUMENTS,
                AgentCapability.FINANCIAL_FACTS,
                AgentCapability.MACRO_SERIES,
            ),
            reason_codes=("hybrid_sources",),
        ),
        "resolved_query": ResolvedQuery(
            query="Compare revenue and rates",
            company_ids=(company_id,),
            metrics=("revenue",),
        ),
        "execution_plan": plan,
    }
    planning_events = project_agent_transition(initial, planned)
    assert [event.event_type for event in planning_events] == [
        "analysis.summary",
        "entities.summary",
        "plan.summary",
    ]

    retrieval_plan = RetrievalPlan(query="query", strategy="hybrid")
    completed: AgentState = {
        **planned,
        "draft_answer": "PRIVATE DRAFT ANSWER",
        "retrieval_results": (
            RetrievalBranchResult(
                branch_id="documents",
                result=AdaptiveRetrievalResponse(
                    query="query",
                    resolved_query=ResolvedQuery(query="query"),
                    plan=retrieval_plan,
                    context=(
                        ContextEvidence(
                            kind="chunk",
                            content="PRIVATE RAW RETRIEVED PASSAGE",
                            citation_label="Risk Factors",
                            source_url="https://example.test/source",
                            source_id="chunk:private",
                            token_count=4,
                        ),
                    ),
                    trace=RetrievalTrace(
                        initial_plan=retrieval_plan,
                        attempts=(),
                        final_context_tokens=0,
                    ),
                ),
            ),
        ),
        "financial_results": (
            FinancialBranchResult(
                branch_id="facts",
                result=FinancialFactQueryResult(
                    query=financial.request,
                    observations=(),
                    available_units=("USD",),
                    warnings=("financial warning",),
                ),
            ),
        ),
        "macro_results": (
            MacroBranchResult(
                branch_id="macro",
                result=FredSeriesResult(
                    query=macro.request,
                    series=(),
                    observations=(),
                    warnings=("macro warning",),
                ),
            ),
        ),
        "calculations": (
            CalculationBranchResult(
                branch_id="growth",
                result=CalculationResult(
                    operation="year_over_year_growth",
                    values=(CalculationPoint(label="2025", value=Decimal("12.5")),),
                    inputs=(
                        NumericObservation(
                            label="Revenue",
                            value=Decimal("100"),
                            unit="USD",
                            source_url="https://example.test/source",
                        ),
                    ),
                    formula="(current / prior - 1) * 100",
                    unit="percent",
                    sources=("https://example.test/source",),
                ),
            ),
        ),
        "branch_outcomes": tuple(
            BranchOutcome(
                branch_id=branch.branch_id,
                kind=branch.kind,
                status=BranchStatus.COMPLETED,
                attempts=1,
            )
            for branch in (retrieval, financial, macro, calculation)
        ),
        "chart_spec": ChartSpecification(
            chart_type="line",
            title="Revenue growth",
            x_label="Date",
            series=(ChartSeries(key="growth", label="Growth", unit="percent"),),
            data=(
                ChartPoint(
                    x=date(2025, 1, 1),
                    values={"growth": Decimal("12.5")},
                    source_urls=("https://example.test/source",),
                ),
            ),
            sources=("https://example.test/source",),
        ),
        "claims": (
            ClaimRecord(
                claim_id="claim:0123456789abcdef",
                text="Revenue grew.",
                evidence_ids=("fact:revenue",),
                sentence_index=0,
            ),
        ),
        "answer_validation": AnswerValidation(
            valid=True,
            claims=(
                ClaimValidation(
                    claim_id="claim:0123456789abcdef",
                    supported=True,
                    evidence_ids=("fact:revenue",),
                    semantic_support=SemanticSupportResult(
                        status=SemanticSupportStatus.SUPPORTED,
                        reason_code="supported",
                        prompt_version="judge.v1",
                    ),
                ),
            ),
            cited_evidence_ids=("fact:revenue",),
        ),
    }
    events = project_agent_transition(planned, completed)
    assert [event.event_type for event in events] == [
        "tool.status",
        "tool.status",
        "tool.status",
        "tool.status",
        "chart.ready",
        "validation.summary",
    ]
    encoded = json.dumps([event.data for event in events], default=str)
    assert "PRIVATE DRAFT ANSWER" not in encoded
    assert "PRIVATE RAW RETRIEVED PASSAGE" not in encoded
    assert "formula" in encoded
    assert "observation_count" in encoded


def test_task_events_expose_status_but_not_task_input_or_result() -> None:
    branch = MacroSeriesBranch(
        branch_id="macro",
        request=FredSeriesQuery(series_ids=("FEDFUNDS",)),
    )
    task_input = {**_state(), "active_branch": branch, "draft_answer": "PRIVATE INPUT"}
    started = task_started_event(
        task_id="task-1",
        node="query_macro_series",
        task_input=task_input,
        attempt=1,
    )
    assert [event.event_type for event in started] == ["node.status", "tool.status"]
    finished = task_finished_event(
        task_id="task-1",
        node="query_macro_series",
        task_input=task_input,
        task_result={
            "draft_answer": "PRIVATE RESULT",
            "trajectory": (
                TrajectoryEvent(
                    node="query_macro_series",
                    status=TrajectoryStatus.COMPLETED,
                    occurred_at=datetime.now(UTC),
                    summary="Branch execution completed.",
                    duration_ms=8,
                ),
            ),
        },
        task_error=None,
        attempt=1,
        duration_ms=10,
    )
    encoded = json.dumps([event.data for event in (*started, finished)], default=str)
    assert "PRIVATE INPUT" not in encoded
    assert "PRIVATE RESULT" not in encoded
    assert finished.data["duration_ms"] == 8


def test_version_two_envelope_rejects_an_event_payload_with_the_wrong_shape() -> None:
    with pytest.raises(ValidationError):
        ResearchEventEnvelope(
            id=1,
            schema_version="2",
            run_id=uuid.uuid4(),
            type="node.status",
            occurred_at=datetime.now(UTC),
            data={"node": "parse_question", "status": "completed"},
        )


def _state() -> AgentState:
    return {
        "run_id": uuid.uuid4(),
        "session_id": "session-1",
        "question": "Question",
        "policy": ExecutionPolicy(),
        "status": AgentRunStatus.RUNNING,
        "messages": (),
        "retrieval_results": (),
        "financial_results": (),
        "macro_results": (),
        "calculations": (),
        "branch_outcomes": (),
        "errors": (),
        "trajectory": (),
        "node_attempts": (),
        "tool_calls_used": 0,
    }
