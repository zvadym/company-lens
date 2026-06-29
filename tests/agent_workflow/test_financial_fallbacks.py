from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_quarterly_missing_financial_facts_fall_back_to_annual_series() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare Cloudflare revenue growth over the last eight quarters.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS, AgentCapability.CALCULATIONS),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            FinancialFactsBranch(
                branch_id="financial",
                request=FinancialFactQuery(
                    company_ids=(COMPANY_ID,),
                    metrics=("revenue",),
                    period_types=("quarter",),
                    limit=24,
                ),
            ),
            CalculationBranch(
                branch_id="growth",
                operation="year_over_year_growth",
                input_refs=("financial",),
                depends_on=("financial",),
            ),
        ),
    )
    model = AnswerTimeoutModelProvider(analysis=analysis, plan=plan)
    tools = QuarterlyMissingAnnualFallbackTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Compare Cloudflare revenue growth over the last eight quarters.",
        session_id="session-annual-fallback-success",
        policy=ExecutionPolicy(max_retries_per_node=0),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert tools.calls["financial"] == 2
    assert [request.period_types for request in tools.financial_requests] == [
        ("quarter",),
        ("annual",),
    ]
    financial = result["financial_results"][-1].result
    assert financial.query.period_types == ("annual",)
    assert "annual_financial_fallback_used" in financial.warnings
    assert result["tool_calls_used"] == 2
    assert result["final_answer"] is not None
    assert "latest value was 25% at 2025-12-31" in result["final_answer"]
    assert result["answer_validation"].valid is True


def test_annual_fallback_deduplicates_restated_periods_before_charting() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Plot Pepsico R&D expense growth over the last eight quarters.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
    )
    facts = FinancialFactsBranch(
        branch_id="financial_rnd_qtr",
        request=FinancialFactQuery(
            company_ids=(COMPANY_ID,),
            metrics=("research_and_development_expense",),
            period_types=("quarter",),
            limit=24,
        ),
    )
    growth = CalculationBranch(
        branch_id="rnd_yoy_growth",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    chart = ChartBranch(
        branch_id="chart",
        chart_type="line",
        dataset_ref=growth.branch_id,
        depends_on=(growth.branch_id,),
        title="Pepsico R&D expense YoY growth",
    )
    model = AnswerTimeoutModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=(facts, growth, chart),
        ),
    )
    tools = QuarterlyMissingDuplicatedAnnualFallbackTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Побудуй line chart YoY R&D expense growth для Pepsico за останні 8 кварталів.",
        session_id="session-annual-fallback-duplicate-chart",
        policy=ExecutionPolicy(max_retries_per_node=0),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert tools.calls["financial"] == 2
    assert result["chart_spec"] is not None
    assert [point.x for point in result["chart_spec"].data] == [
        date(2023, 12, 31),
        date(2024, 12, 31),
        date(2025, 12, 31),
    ]
    calculation = result["calculations"][0].result
    assert [point.observed_at for point in calculation.values] == [
        date(2023, 12, 31),
        date(2024, 12, 31),
        date(2025, 12, 31),
    ]
    assert len(calculation.inputs) == 4
    assert not any(error.code == "invalid_chart_dataset" for error in result["errors"])


def test_financial_missing_after_annual_fallback_abstains_with_explanation() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare Cloudflare revenue growth over the last eight quarters.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS, AgentCapability.CALCULATIONS),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            FinancialFactsBranch(
                branch_id="financial",
                request=FinancialFactQuery(
                    company_ids=(COMPANY_ID,),
                    metrics=("revenue",),
                    period_types=("quarter",),
                    limit=24,
                ),
            ),
            CalculationBranch(
                branch_id="growth",
                operation="year_over_year_growth",
                input_refs=("financial",),
                depends_on=("financial",),
            ),
        ),
    )
    model = FakeModelProvider(analysis=analysis, plan=plan)
    tools = QuarterlyMissingAnnualFallbackTools(annual_observations=False)

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Compare Cloudflare revenue growth over the last eight quarters.",
        session_id="session-annual-fallback-missing",
    )

    assert result["status"] is AgentRunStatus.ABSTAINED
    assert tools.calls["financial"] == 2
    assert ModelPurpose.ANSWER not in model.purposes
    assert result["final_answer"] is not None
    assert "SEC/EDGAR companies" in result["final_answer"]
    assert "annual fallback" in result["final_answer"]
    financial = result["financial_results"][-1].result
    assert financial.observations == ()
    assert "annual_financial_fallback_missing" in financial.warnings


def test_qoq_missing_quarterly_facts_does_not_use_annual_fallback() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Calculate Cloudflare quarter over quarter revenue growth.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS, AgentCapability.CALCULATIONS),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            FinancialFactsBranch(
                branch_id="financial",
                request=FinancialFactQuery(
                    company_ids=(COMPANY_ID,),
                    metrics=("revenue",),
                    period_types=("quarter",),
                    limit=8,
                ),
            ),
            CalculationBranch(
                branch_id="growth",
                operation="quarter_over_quarter_growth",
                input_refs=("financial",),
                depends_on=("financial",),
            ),
        ),
    )
    model = FakeModelProvider(analysis=analysis, plan=plan)
    tools = QuarterlyMissingAnnualFallbackTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Calculate Cloudflare quarter over quarter revenue growth.",
        session_id="session-qoq-no-annual-fallback",
    )

    assert result["status"] is AgentRunStatus.ABSTAINED
    assert tools.calls["financial"] == 1
    assert tools.financial_requests[0].period_types == ("quarter",)
    assert result["final_answer"] is not None
    assert "requires quarterly facts" in result["final_answer"]
