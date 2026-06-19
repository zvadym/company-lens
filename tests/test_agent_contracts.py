from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from company_lens.agent.schemas import (
    AgentCapability,
    AgentError,
    AgentErrorCategory,
    AgentErrorSeverity,
    AgentRunStatus,
    AgentState,
    CalculationBranch,
    ChartBranch,
    DocumentRetrievalBranch,
    ExecutionPlan,
    ExecutionPolicy,
    FinancialFactsBranch,
    MacroSeriesBranch,
    QuestionAnalysis,
    ResearchRoute,
    SessionMessage,
)
from company_lens.financials.schemas import FinancialFactQuery
from company_lens.macro.schemas import FredSeriesQuery
from company_lens.retrieval.adaptive_schemas import AdaptiveRetrievalRequest


def test_question_analysis_validates_capabilities_and_safe_reason_codes() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Chart Cloudflare revenue growth",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        reason_codes=("financial_metric", "chart_requested"),
    )

    assert analysis.route is ResearchRoute.HYBRID
    with pytest.raises(ValidationError, match="chart capability"):
        QuestionAnalysis(
            normalized_question="Chart revenue",
            route=ResearchRoute.STRUCTURED_ONLY,
            chart_requested=True,
        )
    with pytest.raises(ValidationError, match="snake_case"):
        QuestionAnalysis(
            normalized_question="Revenue",
            route=ResearchRoute.STRUCTURED_ONLY,
            reason_codes=("Hidden reasoning",),
        )


def test_execution_plan_requires_unique_acyclic_branches() -> None:
    plan = ExecutionPlan(
        route=ResearchRoute.HYBRID,
        branches=(
            DocumentRetrievalBranch(
                branch_id="documents",
                request=AdaptiveRetrievalRequest(query="Cloudflare risks"),
            ),
            FinancialFactsBranch(
                branch_id="financial_facts",
                request=FinancialFactQuery(metrics=("revenue",)),
            ),
            MacroSeriesBranch(
                branch_id="macro_series",
                request=FredSeriesQuery(series_ids=("FEDFUNDS",)),
            ),
            CalculationBranch(
                branch_id="growth",
                operation="year_over_year_growth",
                input_refs=("financial_facts",),
                depends_on=("financial_facts",),
            ),
            ChartBranch(
                branch_id="chart",
                chart_type="line",
                dataset_ref="growth",
                depends_on=("growth",),
            ),
        ),
        reason_codes=("deterministic_calculation",),
    )

    assert plan.branches[3].depends_on == ("financial_facts",)
    with pytest.raises(ValidationError, match="acyclic"):
        ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=(
                CalculationBranch(
                    branch_id="first",
                    operation="margin",
                    input_refs=("second",),
                    depends_on=("second",),
                ),
                CalculationBranch(
                    branch_id="second",
                    operation="margin",
                    input_refs=("first",),
                    depends_on=("first",),
                ),
            ),
        )


def test_state_uses_immutable_accumulators_and_frozen_contracts() -> None:
    message = SessionMessage(
        role="user",
        content="Compare Cloudflare revenue growth",
        created_at=datetime.now(UTC),
    )
    state: AgentState = {
        "run_id": uuid.uuid4(),
        "session_id": "session-1",
        "question": message.content,
        "policy": ExecutionPolicy(),
        "status": AgentRunStatus.PENDING,
        "messages": (message,),
        "errors": (),
        "trajectory": (),
    }

    assert isinstance(state["messages"], tuple)
    with pytest.raises(ValidationError, match="frozen"):
        message.content = "mutated"


def test_execution_policy_enforces_bounded_limits() -> None:
    assert ExecutionPolicy().max_tool_calls == 10
    with pytest.raises(ValidationError):
        ExecutionPolicy(max_tool_calls=0)
    with pytest.raises(ValidationError):
        ExecutionPolicy(max_retries_per_node=11)


def test_typed_error_exposes_recoverability_without_internal_details() -> None:
    error = AgentError(
        category=AgentErrorCategory.PROVIDER_TIMEOUT,
        severity=AgentErrorSeverity.RECOVERABLE,
        code="openai_timeout",
        message="OpenAI request timed out.",
    )

    assert error.recoverable is True
