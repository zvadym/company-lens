from __future__ import annotations
# ruff: noqa: F403, F405, I001
from .context import *

def test_runtime_overrides_model_selected_retrieval_index() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What risks did Cloudflare report?",
        route=ResearchRoute.RAG_ONLY,
        required_capabilities=(AgentCapability.DOCUMENTS,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.RAG_ONLY,
            branches=(
                DocumentRetrievalBranch(
                    branch_id="documents",
                    request=AdaptiveRetrievalRequest(
                        query="Cloudflare business risks",
                        index_name="model-selected",
                        index_version="model-selected.v1",
                    ),
                ),
            ),
        ),
        texts=("Competition was a reported risk [document:cloudflare-risk].",),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(
        runtime=ResearchAgentRuntime(
            model,
            tools,
            retrieval_index_name="production",
            retrieval_index_version="openai-index.v2",
        )
    ).run("What risks did Cloudflare report?", session_id="session-index")

    assert result["status"] is AgentRunStatus.COMPLETED
    assert tools.retrieval_requests[0].index_name == "production"
    assert tools.retrieval_requests[0].index_version == "openai-index.v2"
    assert tools.retrieval_requests[0].evidence_scope == "documents"


def test_api_only_route_generates_chart_from_macro_series() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Chart the federal funds rate",
        route=ResearchRoute.API_ONLY,
        required_capabilities=(AgentCapability.MACRO_SERIES, AgentCapability.CHART),
        chart_requested=True,
    )
    macro = _macro_branch()
    chart = ChartBranch(
        branch_id="chart",
        chart_type="line",
        dataset_ref=macro.branch_id,
        title="Federal funds rate",
        depends_on=(macro.branch_id,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.API_ONLY, branches=(macro, chart)),
        texts=("The rate was 3.5 percent [macro:fedfunds:2025-12-01].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Chart the federal funds rate", session_id="session-api"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["chart_spec"] is not None
    assert result["chart_spec"].data[0].values == {"macro": Decimal("3.5")}


def test_calculation_route_generates_deterministic_evidence() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Calculate revenue growth",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
    )
    facts = _financial_branch()
    growth = CalculationBranch(
        branch_id="growth",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    plan = ExecutionPlan(route=ResearchRoute.CALCULATION, branches=(facts, growth))
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        texts=("Revenue growth was 25 percent [calculation:growth].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Calculate revenue growth", session_id="session-2"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["calculations"][0].result.values[0].value == Decimal("25.00")
    calculation_evidence = next(
        item for item in result["evidence"] if item.evidence_id == "calculation:growth"
    )
    assert calculation_evidence.metadata.company_id == COMPANY_ID
    assert calculation_evidence.metadata.company_name == "Cloudflare"
    assert calculation_evidence.metadata.metric == "revenue"
    answer_context = next(
        messages[-1].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.ANSWER
    )
    assert '"calculation"' in answer_context
    assert '"values"' in answer_context
    assert '"payload"' not in answer_context


def test_yoy_growth_selects_deduplicated_annual_series_from_mixed_facts() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Calculate revenue growth",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
    )
    facts = FinancialFactsBranch(
        branch_id="financial",
        request=FinancialFactQuery(
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
            period_types=("quarter", "annual"),
            limit=20,
        ),
    )
    growth = CalculationBranch(
        branch_id="growth",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION, branches=(facts, growth)),
        texts=("Revenue growth was 25 percent [calculation:growth].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, MixedPeriodFinancialTools())).run(
        "Calculate revenue growth", session_id="session-many-growth-facts"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    calculation = result["calculations"][0].result
    assert [point.value for point in calculation.values] == [
        Decimal("25.00"),
        Decimal("25.00"),
    ]
    assert [item.observed_at for item in calculation.inputs] == [
        date(2022, 12, 31),
        date(2023, 12, 31),
        date(2024, 12, 31),
    ]


def test_yoy_growth_returns_full_deduplicated_annual_series() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Calculate annual revenue growth",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
    )
    facts = FinancialFactsBranch(
        branch_id="financial",
        request=FinancialFactQuery(
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
            period_types=("annual",),
            fiscal_years=(2023, 2024, 2025),
            limit=20,
        ),
    )
    growth = CalculationBranch(
        branch_id="growth",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION, branches=(facts, growth)),
        texts=("Revenue growth was 25 percent [calculation:growth].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, AnnualSeriesFinancialTools())).run(
        "Calculate annual revenue growth", session_id="session-growth-series"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    calculation = result["calculations"][0].result
    assert [point.observed_at for point in calculation.values] == [
        date(2023, 12, 31),
        date(2024, 12, 31),
        date(2025, 12, 31),
    ]
    assert [point.value for point in calculation.values] == [
        Decimal("25.00"),
        Decimal("25.00"),
        Decimal("25.00"),
    ]
    assert len(calculation.inputs) == 4
    assert calculation.inputs[0].observed_at == date(2022, 12, 31)
