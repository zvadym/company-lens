from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_unsupported_future_projection_cannot_be_promoted_by_planner() -> None:
    invalid_model_analysis = QuestionAnalysis.model_construct(
        normalized_question="What will Cloudflare revenue be in 2035?",
        route=ResearchRoute.UNSUPPORTED,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
        chart_requested=False,
        is_follow_up=False,
        reason_codes=("future_projection", "no_direct_source"),
    )
    model = FakeModelProvider(
        analysis=invalid_model_analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=(
                _financial_branch(),
                CalculationBranch(
                    branch_id="revenue_cagr",
                    operation="cagr",
                    input_refs=("financial",),
                    years=10,
                ),
            ),
        ),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "What will Cloudflare revenue be in 2035?",
        session_id="session-unsupported-future-plan",
    )

    assert result["status"] is AgentRunStatus.ABSTAINED
    assert result["analysis"].route is ResearchRoute.UNSUPPORTED
    assert result["execution_plan"].route is ResearchRoute.UNSUPPORTED
    assert result["execution_plan"].branches == ()
    assert "unsupported_analysis_enforced" in result["execution_plan"].reason_codes
    assert tools.calls["financial"] == 0
    assert tools.calls["calculation"] == 0
