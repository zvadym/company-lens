from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_default_chart_window_plots_quarterly_yoy_growth_series_against_macro() -> None:
    class QuarterlyFinancialAndMacroTools(MonthlyMacroTools):
        def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
            self.calls["financial"] += 1
            return FinancialFactQueryResult(
                query=request,
                observations=tuple(
                    _financial_observation(period_end, value).model_copy(
                        update={"period_type": "quarter", "fiscal_period": fiscal_period}
                    )
                    for period_end, fiscal_period, value in (
                        (date(2024, 3, 31), "Q1", Decimal("100")),
                        (date(2024, 6, 30), "Q2", Decimal("120")),
                        (date(2024, 9, 30), "Q3", Decimal("140")),
                        (date(2025, 3, 31), "Q1", Decimal("125")),
                        (date(2025, 6, 30), "Q2", Decimal("150")),
                        (date(2025, 9, 30), "Q3", Decimal("175")),
                    )
                ),
                available_units=("USD",),
            )

        def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
            self.calls["macro"] += 1
            return FredSeriesResult(
                query=request,
                series=(),
                observations=tuple(
                    FredObservation(
                        series_id="FEDFUNDS",
                        observed_at=observed_at,
                        realtime_start=observed_at,
                        realtime_end=observed_at,
                        value=value,
                        raw_value=str(value),
                        is_missing=False,
                        unit="percent",
                        frequency="Monthly",
                        source_url=f"https://fred.example/FEDFUNDS/{observed_at.isoformat()}",
                    )
                    for observed_at, value in (
                        (date(2025, 3, 1), Decimal("3")),
                        (date(2025, 6, 1), Decimal("4")),
                        (date(2025, 9, 1), Decimal("5")),
                    )
                ),
            )

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
            period_types=("quarter",),
            limit=8,
        ),
    )
    macro = _macro_branch()
    growth = CalculationBranch(
        branch_id="growth",
        operation="quarter_over_quarter_growth",
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
        runtime=ResearchAgentRuntime(model, QuarterlyFinancialAndMacroTools())
    ).run(
        "Plot Cloudflare revenue growth against the federal funds rate.",
        session_id="session-hybrid-default-window-chart",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["chart_spec"] is not None
    assert [series.key for series in result["chart_spec"].series] == ["growth", "macro"]
    assert [point.x for point in result["chart_spec"].data] == [
        date(2025, 3, 31),
        date(2025, 6, 30),
        date(2025, 9, 30),
    ]
    assert [point.values["growth"] for point in result["chart_spec"].data] == [
        Decimal("25.00"),
        Decimal("25.00"),
        Decimal("25.00"),
    ]
    assert [point.values["macro"] for point in result["chart_spec"].data] == [
        Decimal("3"),
        Decimal("4"),
        Decimal("5"),
    ]
