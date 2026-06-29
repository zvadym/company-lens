from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_peer_revenue_growth_chart_reconciles_hybrid_analysis_to_calculation_route() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Plot Cloudflare revenue growth against Netflix revenue growth",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        reason_codes=("two_company_series", "growth_metric", "chart_requested"),
    )
    cloudflare_facts = FinancialFactsBranch(
        branch_id="cloudflare_revenue",
        request=FinancialFactQuery(
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
            period_types=("annual",),
            limit=20,
        ),
    )
    netflix_facts = FinancialFactsBranch(
        branch_id="netflix_revenue",
        request=FinancialFactQuery(
            company_ids=(NETFLIX_ID,),
            metrics=("revenue",),
            period_types=("annual",),
            limit=20,
        ),
    )
    cloudflare_growth = CalculationBranch(
        branch_id="cloudflare_growth",
        operation="year_over_year_growth",
        input_refs=(cloudflare_facts.branch_id,),
        depends_on=(cloudflare_facts.branch_id,),
    )
    netflix_growth = CalculationBranch(
        branch_id="netflix_growth",
        operation="year_over_year_growth",
        input_refs=(netflix_facts.branch_id,),
        depends_on=(netflix_facts.branch_id,),
    )
    chart = ChartBranch(
        branch_id="chart",
        chart_type="line",
        dataset_ref=cloudflare_growth.branch_id,
        title="Cloudflare revenue growth vs Netflix revenue growth",
        depends_on=(cloudflare_growth.branch_id, netflix_growth.branch_id),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.HYBRID,
            branches=(
                cloudflare_facts,
                netflix_facts,
                cloudflare_growth,
                netflix_growth,
                chart,
            ),
            requires_citations=False,
        ),
        texts=("The chart is ready."),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, PeerAnnualFinancialTools())).run(
        "Plot Cloudflare revenue growth against Netflix revenue growth.",
        session_id="session-peer-growth-chart",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["analysis"].route is ResearchRoute.CALCULATION
    assert "reconciled_to_valid_plan" in result["analysis"].reason_codes
    assert result["chart_spec"] is not None
    assert [series.key for series in result["chart_spec"].series] == [
        "cloudflare_growth",
        "netflix_growth",
    ]
    assert [series.label for series in result["chart_spec"].series] == [
        "Cloudflare revenue YoY",
        "Netflix revenue YoY",
    ]
    assert len(result["chart_spec"].data) == 3
    assert result["tool_calls_used"] == 2


def test_hybrid_chart_normalizes_missing_comparison_dependency() -> None:
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
        depends_on=(facts.branch_id, macro.branch_id),
    )
    chart = ChartBranch(
        branch_id="chart",
        chart_type="line",
        dataset_ref="growth",
        title="Revenue growth vs federal funds rate",
        depends_on=("growth",),
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
        session_id="session-hybrid-normalized-chart",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["chart_spec"] is not None
    assert [series.key for series in result["chart_spec"].series] == ["growth", "macro"]


def test_hybrid_chart_aligns_monthly_macro_to_financial_period_dates() -> None:
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

    result = ResearchAgent(
        runtime=ResearchAgentRuntime(model, AnnualFinancialAndMonthlyMacroTools())
    ).run(
        "Plot Cloudflare revenue growth against the federal funds rate.",
        session_id="session-hybrid-monthly-macro-chart",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["chart_spec"] is not None
    assert result["chart_spec"].data[0].x == date(2023, 12, 31)
    assert result["chart_spec"].data[0].values == {
        "growth": Decimal("25.00"),
        "macro": Decimal("5.25"),
    }
