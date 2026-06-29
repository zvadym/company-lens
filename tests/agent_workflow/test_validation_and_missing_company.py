from __future__ import annotations

# ruff: noqa: F403, F405, I001
from .context import *


def test_financial_markdown_table_passes_end_to_end_validation() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare annual revenue growth and explain the drivers",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.DOCUMENTS,
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
    )
    documents = DocumentRetrievalBranch(
        branch_id="documents",
        request=AdaptiveRetrievalRequest(query="Cloudflare growth drivers"),
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
    growth = CalculationBranch(
        branch_id="growth",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    evidence_ids = {year: f"financial_fact:{ANNUAL_FACT_IDS[year]}" for year in range(2022, 2026)}
    rows = "\n".join(
        f"| {year} | {revenue} USD | 25.0% vs. {year - 1} | Form 10-K "
        f"[{evidence_ids[year - 1]}] [{evidence_ids[year]}] [calculation:growth] |"
        for year, revenue in ((2023, 80), (2024, 100), (2025, 125))
    )
    headline_citations = " ".join(f"[{evidence_ids[year]}]" for year in range(2022, 2026))
    headline = (
        "Cloudflare revenue grew 25.0% in 2023, 2024, and 2025 "
        f"[calculation:growth] {headline_citations}."
    )
    answer = f"""{headline}

| Year | Revenue | YoY growth | Supporting filing |
|---|---:|---:|---|
{rows}

Cloudflare identified competition as a material business risk [document:cloudflare-risk].
"""
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.HYBRID,
            branches=(documents, facts, growth),
        ),
        texts=(answer,),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, AnnualSeriesFinancialTools())).run(
        "Compare annual revenue growth and explain the drivers",
        session_id="session-financial-table",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["answer_validation"].valid is True
    assert len(result["claims"]) == 5
    assert result["repair_attempts"] == 0


@pytest.mark.parametrize(
    ("operation", "expected"),
    (("absolute_change", Decimal("11")), ("percentage_change", Decimal("1100.00"))),
)
def test_period_change_uses_first_and_last_observations_from_macro_series(
    operation: str,
    expected: Decimal,
) -> None:
    analysis = QuestionAnalysis(
        normalized_question="How did the federal funds rate change during 2024?",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.MACRO_SERIES,
            AgentCapability.CALCULATIONS,
        ),
    )
    macro = _macro_branch()
    change = CalculationBranch(
        branch_id="change",
        operation=operation,
        input_refs=(macro.branch_id,),
        depends_on=(macro.branch_id,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION, branches=(macro, change)),
        texts=(f"The rate changed by {expected} [calculation:change].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, MonthlyMacroTools())).run(
        "How did the federal funds rate change during 2024?",
        session_id="session-period-change",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    calculation = result["calculations"][0].result
    assert calculation.values[0].value == expected
    assert [item.observed_at for item in calculation.inputs] == [
        date(2024, 1, 1),
        date(2024, 12, 1),
    ]


def test_valid_plan_reconciles_inconsistent_question_classification() -> None:
    analysis = QuestionAnalysis(
        normalized_question="How did the federal funds rate change during 2024?",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
        reason_codes=("financial_data_requested",),
    )
    macro = _macro_branch()
    change = CalculationBranch(
        branch_id="change",
        operation="absolute_change",
        input_refs=(macro.branch_id,),
        depends_on=(macro.branch_id,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.STRUCTURED_ONLY, branches=(macro, change)),
        texts=("The rate changed by 11 percentage points [calculation:change].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, MonthlyMacroTools())).run(
        "How did the federal funds rate change during 2024?",
        session_id="session-reconciled-plan",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["analysis"].route is ResearchRoute.CALCULATION
    assert result["analysis"].required_capabilities == (
        AgentCapability.MACRO_SERIES,
        AgentCapability.CALCULATIONS,
    )
    assert "reconciled_to_valid_plan" in result["analysis"].reason_codes


def test_plan_reconciliation_does_not_drop_explicit_chart_requirement() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Chart the federal funds rate",
        route=ResearchRoute.API_ONLY,
        required_capabilities=(AgentCapability.MACRO_SERIES, AgentCapability.CHART),
        chart_requested=True,
    )
    tools = FakeResearchTools()
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.API_ONLY, branches=(_macro_branch(),)),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Chart the federal funds rate",
        session_id="session-missing-chart",
    )

    assert result["status"] is AgentRunStatus.FAILED
    assert tools.calls["macro"] == 0
    assert any(error.code == "invalid_execution_plan" for error in result["errors"])
