from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *
from .test_operation_reconciliation_failures import ReconciliationResponseProvider
from company_lens.agent.calculation_intents import (
    BranchOperationDecision,
    CalculationIntent,
    OperationReconciliation,
)
from company_lens.agent.schemas import TrajectoryEvent, TrajectoryStatus
from company_lens.agent.workflow import _reconcile_operations


def test_graph_places_reconciliation_between_planning_and_cache_hydration() -> None:
    mermaid = build_research_graph().get_graph().draw_mermaid()

    assert "plan_request --> reconcile_operations" in mermaid
    assert "reconcile_operations --> hydrate_cached_results" in mermaid


def test_consistent_plan_skips_without_a_model_call() -> None:
    provider = ReconciliationResponseProvider(())

    update = _reconcile_operations(
        _state("quarter_over_quarter_growth"),
        Runtime(context=ResearchAgentRuntime(provider, FakeResearchTools())),
    )

    assert provider.purposes == []
    event = cast(tuple[TrajectoryEvent, ...], update["trajectory"])[0]
    assert event.status is TrajectoryStatus.SKIPPED
    assert event.details["required"] is False


def test_qoq_conflict_is_reconciled_and_persisted_for_inheritance() -> None:
    provider = ReconciliationResponseProvider(
        (
            _response("quarter_over_quarter_growth"),
            _response("quarter_over_quarter_growth"),
        )
    )
    runtime = Runtime(context=ResearchAgentRuntime(provider, FakeResearchTools()))
    first = _state("percentage_change")

    first.update(_reconcile_operations(first, runtime))
    first_plan = cast(ExecutionPlan, first["execution_plan"])
    memory = _updated_session_memory(first, 20, promote_current_context=True)
    follow_up = _state("percentage_change")
    follow_up["question"] = "Add MongoDB too."
    follow_up["analysis"] = QuestionAnalysis(
        normalized_question="Add MongoDB too.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
        inherit_previous_calculation_intents=True,
    )
    follow_up["session_memory"] = memory

    follow_up.update(_reconcile_operations(follow_up, runtime))
    follow_up_plan = cast(ExecutionPlan, follow_up["execution_plan"])

    assert _operation(first_plan) == "quarter_over_quarter_growth"
    assert memory.last_execution_plan == first_plan
    assert _operation(follow_up_plan) == "quarter_over_quarter_growth"
    assert provider.purposes == [ModelPurpose.OPERATION_RECONCILIATION] * 2


def test_reconciliation_context_is_typed_and_privacy_bounded() -> None:
    provider = ReconciliationResponseProvider((_response("quarter_over_quarter_growth"),))
    state = _state("percentage_change")

    _reconcile_operations(
        state,
        Runtime(context=ResearchAgentRuntime(provider, FakeResearchTools())),
    )

    context = provider.model_calls[0][1][1].content
    assert '"effective_intents"' in context
    assert '"calculation_branches"' in context
    assert '"operation": "quarter_over_quarter_growth"' in context
    assert '"final_answer"' not in context
    assert '"evidence"' not in context


def _state(operation: str) -> AgentState:
    source = FinancialFactsBranch(
        branch_id="revenue",
        request=FinancialFactQuery(company_ids=(COMPANY_ID,), metrics=("revenue",)),
    )
    state = create_initial_agent_state(
        "Show QoQ revenue growth.",
        session_id="operation-reconciliation-flow",
    )
    state.update(
        {
            "analysis": QuestionAnalysis(
                normalized_question="Show QoQ revenue growth.",
                route=ResearchRoute.CALCULATION,
                required_capabilities=(
                    AgentCapability.FINANCIAL_FACTS,
                    AgentCapability.CALCULATIONS,
                ),
                calculation_intents=(
                    CalculationIntent(
                        operation="quarter_over_quarter_growth",
                        metrics=("revenue",),
                    ),
                ),
            ),
            "resolved_query": ResolvedQuery(
                query="Show QoQ revenue growth.",
                company_ids=(COMPANY_ID,),
                metrics=("revenue",),
            ),
            "execution_plan": ExecutionPlan(
                route=ResearchRoute.CALCULATION,
                branches=(
                    source,
                    CalculationBranch(
                        branch_id="growth",
                        operation=operation,
                        input_refs=(source.branch_id,),
                        depends_on=(source.branch_id,),
                    ),
                ),
            ),
        }
    )
    return state


def _response(operation: str) -> OperationReconciliation:
    return OperationReconciliation(
        branch_operations=(BranchOperationDecision(branch_id="growth", operation=operation),)
    )


def _operation(plan: ExecutionPlan) -> str:
    return next(
        branch.operation for branch in plan.branches if isinstance(branch, CalculationBranch)
    )
