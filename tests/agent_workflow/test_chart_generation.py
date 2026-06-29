from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_dated_growth_calculation_can_generate_chart() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Chart revenue growth",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
    )
    facts = _financial_branch()
    growth = CalculationBranch(
        branch_id="growth",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    chart = ChartBranch(
        branch_id="chart",
        chart_type="line",
        dataset_ref="growth",
        title="Revenue growth",
        depends_on=("growth",),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION, branches=(facts, growth, chart)),
        texts=("Revenue growth was 25 percent [calculation:growth].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Chart revenue growth", session_id="session-6"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["chart_spec"] is not None
    assert result["chart_spec"].data[0].x == date(2025, 12, 31)


def test_chart_branch_defaults_missing_model_chart_fields() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Chart revenue growth",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
    )
    facts_request = FinancialFactQuery(
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
        fiscal_years=(2024, 2025),
    )
    raw_plan = ModelExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            ModelExecutionBranch(
                kind="query_financial_facts",
                branch_id="financial",
                financial_request=facts_request,
            ),
            ModelExecutionBranch(
                kind="calculate_metrics",
                branch_id="growth",
                operation="year_over_year_growth",
                input_refs=("financial",),
                depends_on=("financial",),
            ),
            ModelExecutionBranch(
                kind="generate_chart_spec",
                branch_id="chart",
                depends_on=("growth",),
            ),
        ),
    )
    model = RawPlanModelProvider(
        analysis=analysis,
        raw_plan=raw_plan,
        texts=("Revenue growth was 25 percent [calculation:growth].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Chart revenue growth", session_id="session-chart-defaults"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["chart_spec"] is not None
    assert result["chart_spec"].series[0].key == "growth"


def test_hybrid_chart_can_plot_calculation_against_macro_series() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Plot Cloudflare revenue growth against the federal funds rate",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.MACRO_SERIES,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
    )
    facts = FinancialFactsBranch(
        branch_id="financial",
        request=FinancialFactQuery(
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
            period_types=("annual",),
            limit=20,
        ),
    )
    macro = _macro_branch()
    growth = CalculationBranch(
        branch_id="growth",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    chart = ChartBranch(
        branch_id="chart",
        chart_type="line",
        dataset_ref="growth",
        title="Revenue growth vs federal funds rate",
        depends_on=("growth", macro.branch_id),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.HYBRID,
            branches=(facts, macro, growth, chart),
            requires_citations=False,
        ),
        texts=("Revenue growth and the federal funds rate are plotted together."),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, AnnualFinancialAndMacroTools())).run(
        "Plot Cloudflare revenue growth against the federal funds rate.",
        session_id="session-hybrid-multi-series-chart",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["chart_spec"] is not None
    assert [series.key for series in result["chart_spec"].series] == ["growth", "macro"]
    assert result["chart_spec"].data[0].values == {
        "growth": Decimal("25.00"),
        "macro": Decimal("5.25"),
    }
