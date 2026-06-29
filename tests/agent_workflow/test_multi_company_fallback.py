from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_multi_company_chart_fallback_plan_uses_each_company_series() -> None:
    analysis = QuestionAnalysis(
        normalized_question="compare Cloudflare and Alphabet revenue growth on a chart",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("cross_company_comparison", "chart_explicitly_requested"),
    )
    previous_plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            FinancialFactsBranch(
                branch_id="google_revenue",
                request=FinancialFactQuery(
                    company_ids=(NETFLIX_ID,),
                    metrics=("revenue",),
                ),
            ),
            CalculationBranch(
                branch_id="google_growth",
                operation="quarter_over_quarter_growth",
                input_refs=("google_revenue",),
                depends_on=("google_revenue",),
            ),
        ),
    )
    memory = SessionMemory(last_execution_plan=previous_plan)
    resolved = ResolvedQuery(
        query="тепер порівняй ці компанії на графіку",
        company_ids=(COMPANY_ID, NETFLIX_ID),
        metrics=("revenue",),
    )

    plan = _fallback_multi_company_growth_chart_plan(analysis, resolved, memory)

    assert plan is not None
    assert plan.route is ResearchRoute.CALCULATION
    assert [branch.kind for branch in plan.branches] == [
        "query_financial_facts",
        "calculate_metrics",
        "query_financial_facts",
        "calculate_metrics",
        "generate_chart_spec",
    ]
    assert all(
        branch.operation == "quarter_over_quarter_growth"
        for branch in plan.branches
        if isinstance(branch, CalculationBranch)
    )
    chart = plan.branches[-1]
    assert isinstance(chart, ChartBranch)
    assert chart.depends_on == ("company_1_revenue_growth", "company_2_revenue_growth")


def test_multi_company_chart_fallback_plan_handles_planner_provider_failure() -> None:
    analysis = QuestionAnalysis(
        normalized_question="compare these companies on a chart",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("multi_company_comparison", "explicit_chart_request"),
    )
    model = PlanFailureModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.HYBRID),
        texts=("The comparison chart is ready [calculation:company_1_revenue_growth].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, PeerAnnualFinancialTools())).run(
        "Compare these companies on a chart.",
        session_id="session-plan-failure-chart-fallback",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert "deterministic_multi_company_growth_chart_plan" in result["execution_plan"].reason_codes
    assert result["chart_spec"] is not None
    assert len(result["chart_spec"].series) == 2
    assert any(error.code == "openai_unexpected" for error in result["errors"])


def test_multi_company_chart_fallback_replaces_under_scoped_model_plan() -> None:
    analysis = QuestionAnalysis(
        normalized_question="compare these companies on a chart",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.MACRO_SERIES,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("multi_company_comparison", "explicit_chart_request"),
    )
    previous_plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            FinancialFactsBranch(
                branch_id="previous_revenue",
                request=FinancialFactQuery(
                    company_ids=(COMPANY_ID,),
                    metrics=("revenue",),
                ),
            ),
            CalculationBranch(
                branch_id="previous_growth",
                operation="quarter_over_quarter_growth",
                input_refs=("previous_revenue",),
                depends_on=("previous_revenue",),
            ),
        ),
    )
    under_scoped_plan = ExecutionPlan(
        route=ResearchRoute.STRUCTURED_ONLY,
        branches=(
            FinancialFactsBranch(
                branch_id="company_revenue_quarters",
                request=FinancialFactQuery(
                    company_ids=(COMPANY_ID, NETFLIX_ID),
                    metrics=("revenue",),
                ),
            ),
            ChartBranch(
                branch_id="compare_revenue_chart",
                chart_type="line",
                dataset_ref="company_revenue_quarters",
                depends_on=("company_revenue_quarters",),
                title="Revenue comparison by quarter",
            ),
        ),
    )
    model = FakeModelProvider(analysis=analysis, plan=under_scoped_plan)
    state = create_initial_agent_state(
        "Compare these companies on a chart.",
        session_id="session-under-scoped-chart-fallback",
    )
    state["analysis"] = analysis
    state["resolved_query"] = ResolvedQuery(
        query="Compare these companies on a chart.",
        company_ids=(COMPANY_ID, NETFLIX_ID),
        metrics=("revenue",),
    )
    state["session_memory"] = SessionMemory(last_execution_plan=previous_plan)

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    plan = update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    assert "deterministic_multi_company_growth_chart_plan" in plan.reason_codes
    assert [branch.kind for branch in plan.branches] == [
        "query_financial_facts",
        "calculate_metrics",
        "query_financial_facts",
        "calculate_metrics",
        "generate_chart_spec",
    ]
    assert all(
        branch.operation == "year_over_year_growth"
        for branch in plan.branches
        if isinstance(branch, CalculationBranch)
    )
    reconciled = update["analysis"]
    assert isinstance(reconciled, QuestionAnalysis)
    assert reconciled.route is ResearchRoute.CALCULATION
    assert AgentCapability.MACRO_SERIES not in reconciled.required_capabilities
    assert AgentCapability.CALCULATIONS in reconciled.required_capabilities
