from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import cast

import pytest
from pydantic import BaseModel

from company_lens.agent import (
    AgentCapability,
    AgentError,
    AgentErrorCategory,
    AgentErrorSeverity,
    AgentRunStatus,
    ExecutionPlan,
    ExecutionPolicy,
    FinancialFactsBranch,
    MacroSeriesBranch,
    ModelMessage,
    ModelPurpose,
    QuestionAnalysis,
    ResearchAgent,
    ResearchAgentRuntime,
    ResearchRoute,
    ResearchToolError,
    StructuredModelResult,
    TextModelResult,
)
from company_lens.agent.model import ModelProviderError
from company_lens.agent.schemas import (
    CalculationBranch,
    ChartBranch,
    DocumentRetrievalBranch,
    ModelExecutionBranch,
    ModelExecutionPlan,
)
from company_lens.financials.schemas import (
    FinancialFactObservation,
    FinancialFactQuery,
    FinancialFactQueryResult,
)
from company_lens.macro.schemas import (
    FredObservation,
    FredSeriesQuery,
    FredSeriesResult,
)
from company_lens.retrieval.adaptive_schemas import (
    AdaptiveRetrievalRequest,
    AdaptiveRetrievalResponse,
    ContextEvidence,
    ResolvedQuery,
    RetrievalPlan,
    RetrievalTrace,
)

COMPANY_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
FACT_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")
ANNUAL_FACT_IDS = {
    year: uuid.uuid5(uuid.NAMESPACE_DNS, f"company-lens-test-revenue-{year}")
    for year in range(2022, 2026)
}


class FakeModelProvider:
    def __init__(
        self,
        *,
        analysis: QuestionAnalysis,
        plan: ExecutionPlan,
        texts: Sequence[str] = (),
    ) -> None:
        self.analysis = analysis
        self.plan = plan
        self.texts = list(texts)
        self.purposes: list[ModelPurpose] = []
        self.model_calls: list[tuple[ModelPurpose, tuple[ModelMessage, ...]]] = []

    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        self.purposes.append(purpose)
        self.model_calls.append((purpose, tuple(messages)))
        if output_type is QuestionAnalysis:
            output: BaseModel = self.analysis
        elif output_type is ModelExecutionPlan:
            output = _model_execution_plan(self.plan)
        else:
            raise AssertionError(f"Unexpected structured output type: {output_type}")
        return StructuredModelResult[OutputT](
            model="fake-planning",
            response_id=f"response-{purpose}",
            output=cast(OutputT, output),
        )

    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult:
        self.purposes.append(purpose)
        self.model_calls.append((purpose, tuple(messages)))
        return TextModelResult(
            model="fake-answer",
            response_id=f"response-{purpose}-{len(self.purposes)}",
            text=self.texts.pop(0),
        )


class RepairTimeoutModelProvider(FakeModelProvider):
    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult:
        if purpose is ModelPurpose.REPAIR:
            self.purposes.append(purpose)
            raise ModelProviderError(
                AgentError(
                    category=AgentErrorCategory.PROVIDER_TIMEOUT,
                    severity=AgentErrorSeverity.RECOVERABLE,
                    code="openai_timeout",
                    message="OpenAI request timed out.",
                )
            )
        return super().generate_text(messages, purpose=purpose)


class FakeResearchTools:
    def __init__(self, *, synchronize_sources: bool = False) -> None:
        self.calls: defaultdict[str, int] = defaultdict(int)
        self.thread_ids: set[int] = set()
        self.retrieval_requests: list[AdaptiveRetrievalRequest] = []
        self.barrier = threading.Barrier(2) if synchronize_sources else None

    def resolve_entities(self, query: str) -> ResolvedQuery:
        self.calls["resolve"] += 1
        return ResolvedQuery(query=query, company_ids=(COMPANY_ID,), metrics=("revenue",))

    def retrieve_documents(self, request: AdaptiveRetrievalRequest) -> AdaptiveRetrievalResponse:
        self.calls["retrieval"] += 1
        self.retrieval_requests.append(request)
        plan = RetrievalPlan(query=request.query, strategy="summary_only")
        return AdaptiveRetrievalResponse(
            query=request.query,
            resolved_query=ResolvedQuery(query=request.query, company_ids=(COMPANY_ID,)),
            plan=plan,
            context=(
                ContextEvidence(
                    kind="document_summary",
                    content="Cloudflare identified competition as a material business risk.",
                    citation_label="document:cloudflare-risk",
                    source_url="https://sec.example/risk",
                    source_id="cloudflare-risk",
                    company_id=COMPANY_ID,
                    company_name="Cloudflare",
                    token_count=10,
                ),
            ),
            trace=RetrievalTrace(
                initial_plan=plan,
                attempts=(),
                final_context_tokens=10,
            ),
        )

    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self._synchronize("financial")
        return FinancialFactQueryResult(
            query=request,
            observations=(
                _financial_observation(date(2024, 12, 31), Decimal("100")),
                _financial_observation(date(2025, 12, 31), Decimal("125")),
            ),
            available_units=("USD",),
        )

    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        self._synchronize("macro")
        return FredSeriesResult(
            query=request,
            series=(),
            observations=(
                FredObservation(
                    series_id="FEDFUNDS",
                    observed_at=date(2025, 12, 1),
                    realtime_start=date(2025, 12, 1),
                    realtime_end=date(2025, 12, 1),
                    value=Decimal("3.5"),
                    raw_value="3.5",
                    is_missing=False,
                    unit="percent",
                    frequency="Monthly",
                    source_url="https://fred.example/FEDFUNDS",
                ),
            ),
        )

    def _synchronize(self, name: str) -> None:
        self.calls[name] += 1
        self.thread_ids.add(threading.get_ident())
        if self.barrier is not None:
            self.barrier.wait(timeout=2)


class MixedPeriodFinancialTools(FakeResearchTools):
    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        annual_2023 = _financial_observation(date(2023, 12, 31), Decimal("100"))
        comparative_2023 = annual_2023.model_copy(
            update={
                "id": uuid.uuid4(),
                "fiscal_year": 2024,
                "filed_date": date(2025, 2, 20),
                "accession_number": "2024-comparative",
            }
        )
        return FinancialFactQueryResult(
            query=request,
            observations=(
                _financial_observation(date(2022, 12, 31), Decimal("80")),
                _financial_observation(date(2023, 3, 31), Decimal("20")).model_copy(
                    update={"period_type": "quarter", "fiscal_period": "Q1"}
                ),
                annual_2023,
                comparative_2023,
                _financial_observation(date(2024, 12, 31), Decimal("125")),
            ),
            available_units=("USD",),
        )


class AnnualSeriesFinancialTools(FakeResearchTools):
    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        annual = tuple(
            _financial_observation(date(year, 12, 31), value).model_copy(
                update={"id": ANNUAL_FACT_IDS[year]}
            )
            for year, value in zip(
                range(2022, 2026),
                (Decimal("64"), Decimal("80"), Decimal("100"), Decimal("125")),
                strict=True,
            )
        )
        comparative_2023 = annual[1].model_copy(
            update={
                "id": uuid.uuid4(),
                "filed_date": date(2025, 2, 20),
                "accession_number": "2023-comparative",
            }
        )
        return FinancialFactQueryResult(
            query=request,
            observations=(*annual, comparative_2023),
            available_units=("USD",),
        )


class FlakyFinancialTools(FakeResearchTools):
    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        if self.calls["financial"] == 1:
            raise ResearchToolError(
                AgentError(
                    category=AgentErrorCategory.TOOL,
                    severity=AgentErrorSeverity.RECOVERABLE,
                    code="temporary_tool_failure",
                    message="Temporary tool failure.",
                )
            )
        self.calls["financial"] -= 1
        return super().query_financial_facts(request)


class BrokenMacroTools(FakeResearchTools):
    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        self.calls["macro"] += 1
        raise ResearchToolError(
            AgentError(
                category=AgentErrorCategory.TOOL,
                severity=AgentErrorSeverity.TERMINAL,
                code="macro_unavailable",
                message="Macro data is unavailable.",
            )
        )


def test_hybrid_source_branches_run_concurrently_and_merge_stably() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare revenue and rates",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.MACRO_SERIES,
        ),
        reason_codes=("financial_macro_comparison",),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.HYBRID,
        branches=(_financial_branch(), _macro_branch()),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        texts=(
            "Revenue was 125 USD [financial_fact:22222222-2222-2222-2222-222222222222] "
            "and the rate was 3.5 percent [macro:fedfunds:2025-12-01].",
        ),
    )
    tools = FakeResearchTools(synchronize_sources=True)

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Compare revenue and rates", session_id="session-1"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["tool_calls_used"] == 2
    assert len(tools.thread_ids) == 2
    assert [item.evidence_id for item in result["evidence"]] == sorted(
        item.evidence_id for item in result["evidence"]
    )
    assert len(result["citations"]) == 2


def test_rag_only_route_uses_document_retrieval() -> None:
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
                    request=AdaptiveRetrievalRequest(query="Cloudflare business risks"),
                ),
            ),
        ),
        texts=("Competition was a reported risk [document:cloudflare-risk].",),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "What risks did Cloudflare report?", session_id="session-rag"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert tools.calls["retrieval"] == 1


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


def test_invalid_citation_is_repaired_once() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What was revenue?",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.STRUCTURED_ONLY,
            branches=(_financial_branch(),),
        ),
        texts=(
            "Revenue was 125 USD [invented:evidence].",
            "Revenue was 125 USD [financial_fact:22222222-2222-2222-2222-222222222222].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "What was revenue?", session_id="session-3"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["repair_attempts"] == 1
    assert ModelPurpose.REPAIR in model.purposes
    assert result["answer_validation"].valid is True
    repair_context = next(
        messages[-1].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.REPAIR
    )
    assert '"payload"' not in repair_context
    assert "financial_fact:22222222-2222-2222-2222-222222222222" in repair_context


def test_repair_timeout_is_not_retried_by_general_node_policy() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What was revenue?",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
    )
    model = RepairTimeoutModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.STRUCTURED_ONLY,
            branches=(_financial_branch(),),
        ),
        texts=("Revenue was 125 USD [invented:evidence].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "What was revenue?",
        session_id="session-repair-timeout",
        policy=ExecutionPolicy(max_retries_per_node=2),
    )

    assert result["status"] is AgentRunStatus.ABSTAINED
    assert model.purposes.count(ModelPurpose.REPAIR) == 1
    assert any(error.code == "openai_timeout" for error in result["errors"])


def test_recoverable_tool_failure_retries_within_global_call_budget() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What was revenue?",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.STRUCTURED_ONLY,
            branches=(_financial_branch(),),
        ),
        texts=("Revenue was 125 USD [financial_fact:22222222-2222-2222-2222-222222222222].",),
    )
    tools = FlakyFinancialTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "What was revenue?",
        session_id="session-retry",
        policy=ExecutionPolicy(max_tool_calls=2, max_retries_per_node=2),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert tools.calls["financial"] == 2
    assert result["tool_calls_used"] == 2


def test_optional_branch_failure_produces_partial_answer() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare revenue with rates if available",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.MACRO_SERIES,
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.HYBRID,
            branches=(_financial_branch(), _macro_branch().model_copy(update={"optional": True})),
        ),
        texts=(
            "Revenue was 125 USD; macro data was unavailable "
            "[financial_fact:22222222-2222-2222-2222-222222222222].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, BrokenMacroTools())).run(
        "Compare revenue with rates if available", session_id="session-partial"
    )

    assert result["status"] is AgentRunStatus.PARTIAL
    assert result["final_answer"] is not None
    assert any(error.code == "macro_unavailable" for error in result["errors"])


def test_unsupported_question_abstains_without_answer_generation() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Write a poem",
        route=ResearchRoute.UNSUPPORTED,
        reason_codes=("outside_research_scope",),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.UNSUPPORTED),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Write a poem", session_id="session-4"
    )

    assert result["status"] is AgentRunStatus.ABSTAINED
    assert result["final_answer"] is None
    assert ModelPurpose.ANSWER not in model.purposes
    assert result["tool_calls_used"] == 0


def test_over_budget_plan_fails_before_source_calls() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare revenue and rates",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.MACRO_SERIES,
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.HYBRID,
            branches=(_financial_branch(), _macro_branch()),
        ),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Compare revenue and rates",
        session_id="session-5",
        policy=ExecutionPolicy(max_tool_calls=1),
    )

    assert result["status"] is AgentRunStatus.FAILED
    assert tools.calls["financial"] == 0
    assert tools.calls["macro"] == 0
    assert any(error.code == "invalid_execution_plan" for error in result["errors"])


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


def _financial_branch() -> FinancialFactsBranch:
    return FinancialFactsBranch(
        branch_id="financial",
        request=FinancialFactQuery(
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
            fiscal_years=(2024, 2025),
        ),
    )


def _macro_branch() -> MacroSeriesBranch:
    return MacroSeriesBranch(
        branch_id="macro",
        request=FredSeriesQuery(series_ids=("FEDFUNDS",)),
    )


class MonthlyMacroTools(FakeResearchTools):
    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        self.calls["macro"] += 1
        return FredSeriesResult(
            query=request,
            series=(),
            observations=tuple(
                FredObservation(
                    series_id="FEDFUNDS",
                    observed_at=date(2024, month, 1),
                    realtime_start=date(2024, month, 1),
                    realtime_end=date(2024, month, 1),
                    value=Decimal(month),
                    raw_value=str(month),
                    is_missing=False,
                    unit="percent",
                    frequency="Monthly",
                    source_url="https://fred.example/FEDFUNDS",
                )
                for month in range(1, 13)
            ),
        )


def _model_execution_plan(plan: ExecutionPlan) -> ModelExecutionPlan:
    branches: list[ModelExecutionBranch] = []
    for branch in plan.branches:
        common: dict[str, object] = {
            "kind": branch.kind,
            "branch_id": branch.branch_id,
            "depends_on": branch.depends_on,
            "optional": branch.optional,
        }
        if isinstance(branch, DocumentRetrievalBranch):
            common["retrieval_request"] = branch.request
        elif isinstance(branch, FinancialFactsBranch):
            common["financial_request"] = branch.request
        elif isinstance(branch, MacroSeriesBranch):
            common["macro_request"] = branch.request
        elif isinstance(branch, CalculationBranch):
            common.update(
                {
                    "operation": branch.operation,
                    "input_refs": branch.input_refs,
                    "years": float(branch.years) if branch.years is not None else None,
                    "window": branch.window,
                    "base": float(branch.base),
                }
            )
        else:
            common.update(
                {
                    "chart_type": branch.chart_type,
                    "dataset_ref": branch.dataset_ref,
                    "title": branch.title,
                    "x_label": branch.x_label,
                }
            )
        branches.append(ModelExecutionBranch.model_validate(common))
    return ModelExecutionPlan(
        route=plan.route,
        branches=tuple(branches),
        requires_citations=plan.requires_citations,
        reason_codes=plan.reason_codes,
    )


def _financial_observation(period_end: date, value: Decimal) -> FinancialFactObservation:
    return FinancialFactObservation(
        id=FACT_ID,
        company_id=COMPANY_ID,
        company_name="Cloudflare",
        ticker="NET",
        metric="revenue",
        value=value,
        unit="USD",
        period_start=date(period_end.year, 1, 1),
        period_end=period_end,
        period_type="annual",
        fiscal_year=period_end.year,
        fiscal_period="FY",
        form="10-K",
        filed_date=period_end,
        accession_number=f"{period_end.year}-fixture",
        taxonomy="us-gaap",
        concept="Revenue",
        frame=None,
        is_amendment=False,
        has_conflict=False,
        mapping_version="v1",
        source_url=f"https://sec.example/{period_end.year}",
    )
