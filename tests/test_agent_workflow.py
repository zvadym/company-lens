from __future__ import annotations

import threading
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import cast

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

    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        self.purposes.append(purpose)
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
        return TextModelResult(
            model="fake-answer",
            response_id=f"response-{purpose}-{len(self.purposes)}",
            text=self.texts.pop(0),
        )


class FakeResearchTools:
    def __init__(self, *, synchronize_sources: bool = False) -> None:
        self.calls: defaultdict[str, int] = defaultdict(int)
        self.thread_ids: set[int] = set()
        self.barrier = threading.Barrier(2) if synchronize_sources else None

    def resolve_entities(self, query: str) -> ResolvedQuery:
        self.calls["resolve"] += 1
        return ResolvedQuery(query=query, company_ids=(COMPANY_ID,), metrics=("revenue",))

    def retrieve_documents(self, request: AdaptiveRetrievalRequest) -> AdaptiveRetrievalResponse:
        self.calls["retrieval"] += 1
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
    assert any(item.evidence_id == "calculation:growth" for item in result["evidence"])


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


def test_scalar_calculation_chart_fails_without_fabricating_answer() -> None:
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
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Chart revenue growth", session_id="session-6"
    )

    assert result["status"] is AgentRunStatus.FAILED
    assert result["final_answer"] is None
    assert any(error.code == "invalid_chart_dataset" for error in result["errors"])


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
