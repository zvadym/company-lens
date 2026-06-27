from __future__ import annotations

import json
import threading
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import cast

import pytest
from langgraph.runtime import Runtime
from pydantic import BaseModel

from company_lens.agent import (
    AgentCapability,
    AgentError,
    AgentErrorCategory,
    AgentErrorSeverity,
    AgentRunStatus,
    BranchOutcome,
    BranchStatus,
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
    CalculationBranchResult,
    ChartBranch,
    CompanyMentionCandidate,
    CompanyMentionExtraction,
    DocumentRetrievalBranch,
    ModelExecutionBranch,
    ModelExecutionPlan,
    ResearchFrame,
    SessionArtifactContext,
    SessionMemory,
)
from company_lens.agent.workflow import (
    _fallback_multi_company_growth_chart_plan,
    _generate_chart_spec,
    _merge_follow_up_if_needed,
    _merge_follow_up_resolution,
    _parse_question,
    _plan_request,
    _prepare_company_data,
    _resolve_entities,
    _updated_session_memory,
    build_research_graph,
    create_initial_agent_state,
)
from company_lens.analytics.schemas import CalculationPoint, CalculationResult
from company_lens.financials.schemas import (
    FinancialFactObservation,
    FinancialFactQuery,
    FinancialFactQueryResult,
)
from company_lens.ingestion.on_demand import CompanyDataPreparationResult
from company_lens.macro.schemas import (
    FredObservation,
    FredSeriesQuery,
    FredSeriesResult,
)
from company_lens.retrieval.adaptive_schemas import (
    AdaptiveRetrievalRequest,
    AdaptiveRetrievalResponse,
    ContextEvidence,
    EntityCandidate,
    EntityResolution,
    ResolvedQuery,
    RetrievalPlan,
    RetrievalTrace,
)
from company_lens.retrieval.resolution import public_company_resolution

COMPANY_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
NETFLIX_ID = uuid.UUID("33333333-3333-3333-3333-333333333333")
APPLE_ID = uuid.UUID("44444444-4444-4444-4444-444444444444")
ZOOM_ID = uuid.UUID("55555555-5555-5555-5555-555555555555")
NOKIA_ID = uuid.UUID("66666666-6666-6666-6666-666666666666")
MICROSOFT_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
AMAZON_ID = uuid.UUID("88888888-8888-8888-8888-888888888888")
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
        company_extraction: CompanyMentionExtraction | None = None,
        texts: Sequence[str] = (),
    ) -> None:
        self.analysis = analysis
        self.plan = plan
        self.company_extraction = company_extraction or CompanyMentionExtraction()
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
        elif output_type is CompanyMentionExtraction:
            output = self.company_extraction
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


class RawPlanModelProvider(FakeModelProvider):
    def __init__(
        self,
        *,
        analysis: QuestionAnalysis,
        raw_plan: ModelExecutionPlan,
        texts: Sequence[str] = (),
    ) -> None:
        super().__init__(analysis=analysis, plan=ExecutionPlan(route=raw_plan.route), texts=texts)
        self.raw_plan = raw_plan

    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        if output_type is not ModelExecutionPlan:
            return super().generate_structured(messages, output_type, purpose=purpose)
        self.purposes.append(purpose)
        self.model_calls.append((purpose, tuple(messages)))
        return StructuredModelResult[OutputT](
            model="fake-planning",
            response_id=f"response-{purpose}",
            output=cast(OutputT, self.raw_plan),
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


class AnswerTimeoutModelProvider(FakeModelProvider):
    def generate_text(
        self,
        messages: Sequence[ModelMessage],
        *,
        purpose: ModelPurpose,
    ) -> TextModelResult:
        if purpose is ModelPurpose.ANSWER:
            self.purposes.append(purpose)
            self.model_calls.append((purpose, tuple(messages)))
            raise ModelProviderError(
                AgentError(
                    category=AgentErrorCategory.PROVIDER_TIMEOUT,
                    severity=AgentErrorSeverity.RECOVERABLE,
                    code="openai_timeout",
                    message="OpenAI request timed out.",
                )
            )
        return super().generate_text(messages, purpose=purpose)


class ParseFailureModelProvider(FakeModelProvider):
    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        if purpose is ModelPurpose.PARSE:
            self.purposes.append(purpose)
            self.model_calls.append((purpose, tuple(messages)))
            raise ModelProviderError(
                AgentError(
                    category=AgentErrorCategory.INTERNAL,
                    severity=AgentErrorSeverity.TERMINAL,
                    code="openai_unexpected",
                    message="Unexpected OpenAI provider failure.",
                )
            )
        return super().generate_structured(messages, output_type, purpose=purpose)


class PlanFailureModelProvider(FakeModelProvider):
    def generate_structured[OutputT: BaseModel](
        self,
        messages: Sequence[ModelMessage],
        output_type: type[OutputT],
        *,
        purpose: ModelPurpose,
    ) -> StructuredModelResult[OutputT]:
        if purpose is ModelPurpose.PLAN:
            self.purposes.append(purpose)
            self.model_calls.append((purpose, tuple(messages)))
            raise ModelProviderError(
                AgentError(
                    category=AgentErrorCategory.INTERNAL,
                    severity=AgentErrorSeverity.TERMINAL,
                    code="openai_unexpected",
                    message="Unexpected OpenAI provider failure.",
                )
            )
        return super().generate_structured(messages, output_type, purpose=purpose)


class FakeResearchTools:
    def __init__(self, *, synchronize_sources: bool = False) -> None:
        self.calls: defaultdict[str, int] = defaultdict(int)
        self.thread_ids: set[int] = set()
        self.retrieval_requests: list[AdaptiveRetrievalRequest] = []
        self.barrier = threading.Barrier(2) if synchronize_sources else None

    def resolve_entities(self, query: str) -> ResolvedQuery:
        self.calls["resolve"] += 1
        return ResolvedQuery(query=query, company_ids=(COMPANY_ID,), metrics=("revenue",))

    def resolve_non_company_entities(self, query: str) -> ResolvedQuery:
        resolved = self.resolve_entities(query)
        has_company_entities = any(
            entity.kind in {"company", "public_company"} for entity in resolved.entities
        )
        return resolved.model_copy(
            update={
                "entities": tuple(
                    entity
                    for entity in resolved.entities
                    if entity.kind not in {"company", "public_company"}
                ),
                "company_ids": () if has_company_entities else resolved.company_ids,
            }
        )

    def resolve_public_company_mentions(
        self,
        candidates: Sequence[CompanyMentionCandidate],
    ) -> tuple[EntityResolution, ...]:
        self.calls["resolve_public_company_mentions"] += 1
        return ()

    def prepare_companies(
        self,
        *,
        tickers: tuple[str, ...],
        company_ids: tuple[str, ...],
        index_name: str,
        index_version: str,
    ) -> CompanyDataPreparationResult:
        self.calls["prepare"] += 1
        return CompanyDataPreparationResult(
            status="skipped",
            requested_tickers=tickers,
            skipped_tickers=tickers,
            prepared_tickers=(),
        )

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


class AnnualMacroTools(FakeResearchTools):
    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        self.calls["macro"] += 1
        return FredSeriesResult(
            query=request,
            series=(),
            observations=tuple(
                FredObservation(
                    series_id="FEDFUNDS",
                    observed_at=date(year, 12, 31),
                    realtime_start=date(year, 12, 31),
                    realtime_end=date(year, 12, 31),
                    value=value,
                    raw_value=str(value),
                    is_missing=False,
                    unit="percent",
                    frequency="Annual",
                    source_url=f"https://fred.example/FEDFUNDS/{year}",
                )
                for year, value in (
                    (2023, Decimal("5.25")),
                    (2024, Decimal("5.00")),
                    (2025, Decimal("4.50")),
                )
            ),
        )


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


class QuarterlyMissingAnnualFallbackTools(FakeResearchTools):
    def __init__(self, *, annual_observations: bool = True) -> None:
        super().__init__()
        self.annual_observations = annual_observations
        self.financial_requests: list[FinancialFactQuery] = []

    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        self.financial_requests.append(request)
        if request.period_types == ("quarter",):
            return FinancialFactQueryResult(
                query=request,
                observations=(),
                available_units=(),
                warnings=("no_matching_financial_facts",),
            )
        observations = (
            tuple(
                _financial_observation(date(year, 12, 31), value).model_copy(
                    update={"id": ANNUAL_FACT_IDS[year]}
                )
                for year, value in zip(
                    range(2022, 2026),
                    (Decimal("64"), Decimal("80"), Decimal("100"), Decimal("125")),
                    strict=True,
                )
            )
            if self.annual_observations
            else ()
        )
        return FinancialFactQueryResult(
            query=request,
            observations=observations,
            available_units=("USD",) if observations else (),
            warnings=() if observations else ("no_matching_financial_facts",),
        )


class QuarterlyMissingDuplicatedAnnualFallbackTools(QuarterlyMissingAnnualFallbackTools):
    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        if request.period_types == ("quarter",):
            return super().query_financial_facts(request)
        self.calls["financial"] += 1
        self.financial_requests.append(request)
        rows = (
            (2022, Decimal("64"), "FY", date(2023, 2, 1)),
            (2023, Decimal("80"), "FY", date(2024, 2, 1)),
            (2023, Decimal("80"), None, date(2025, 7, 1)),
            (2024, Decimal("100"), "FY", date(2025, 2, 1)),
            (2024, Decimal("100"), None, date(2026, 7, 1)),
            (2025, Decimal("125"), "FY", date(2026, 2, 1)),
        )
        observations = tuple(
            _financial_observation(date(year, 12, 31), value).model_copy(
                update={
                    "id": uuid.uuid5(
                        uuid.NAMESPACE_DNS,
                        f"duplicated-annual-{year}-{fiscal_period}-{filed_date.isoformat()}",
                    ),
                    "company_name": "PEPSICO INC",
                    "ticker": "PEP",
                    "metric": request.metrics[0],
                    "fiscal_period": fiscal_period,
                    "filed_date": filed_date,
                    "accession_number": filed_date.isoformat(),
                    "source_url": f"https://sec.example/pep/{filed_date.isoformat()}",
                }
            )
            for year, value, fiscal_period, filed_date in rows
        )
        return FinancialFactQueryResult(
            query=request,
            observations=observations,
            available_units=("USD",),
        )


class PeerAnnualFinancialTools(FakeResearchTools):
    def resolve_entities(self, query: str) -> ResolvedQuery:
        self.calls["resolve"] += 1
        return ResolvedQuery(
            query=query,
            company_ids=(COMPANY_ID, NETFLIX_ID),
            metrics=("revenue",),
        )

    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        company_id = request.company_ids[0]
        if company_id == NETFLIX_ID:
            company_name = "Netflix"
            ticker = "NFLX"
            values = (Decimal("100"), Decimal("110"), Decimal("132"), Decimal("165"))
        else:
            company_name = "Cloudflare"
            ticker = "NET"
            values = (Decimal("64"), Decimal("80"), Decimal("100"), Decimal("125"))
        return FinancialFactQueryResult(
            query=request,
            observations=tuple(
                _financial_observation(date(year, 12, 31), value).model_copy(
                    update={
                        "id": uuid.uuid5(uuid.NAMESPACE_DNS, f"{company_id}-{year}"),
                        "company_id": company_id,
                        "company_name": company_name,
                        "ticker": ticker,
                    }
                )
                for year, value in zip(range(2022, 2026), values, strict=True)
            ),
            available_units=("USD",),
        )


class AnnualFinancialAndMacroTools(AnnualMacroTools, AnnualSeriesFinancialTools):
    pass


class AnnualFinancialAndMonthlyMacroTools(AnnualSeriesFinancialTools):
    def query_macro_series(self, request: FredSeriesQuery) -> FredSeriesResult:
        self.calls["macro"] += 1
        return FredSeriesResult(
            query=request,
            series=(),
            observations=tuple(
                FredObservation(
                    series_id="FEDFUNDS",
                    observed_at=date(year, 12, 1),
                    realtime_start=date(year, 12, 1),
                    realtime_end=date(year, 12, 1),
                    value=value,
                    raw_value=str(value),
                    is_missing=False,
                    unit="percent",
                    frequency="Monthly",
                    source_url=f"https://fred.example/FEDFUNDS/{year}",
                )
                for year, value in (
                    (2023, Decimal("5.25")),
                    (2024, Decimal("5.00")),
                    (2025, Decimal("4.50")),
                )
            ),
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


class PunctuatedCompanyFinancialTools(FakeResearchTools):
    def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
        self.calls["financial"] += 1
        return FinancialFactQueryResult(
            query=request,
            observations=(
                _financial_observation(date(2025, 12, 31), Decimal("125")).model_copy(
                    update={"company_name": "Elastic N.V.", "ticker": "ESTC"}
                ),
            ),
            available_units=("USD",),
        )


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
    answer_messages = next(
        messages for purpose, messages in model.model_calls if purpose is ModelPurpose.ANSWER
    )
    assert "untrusted data" in answer_messages[0].content
    assert '"trust": "untrusted_external_data"' in answer_messages[1].content


def test_previous_chart_period_question_answers_from_session_memory_without_rag() -> None:
    analysis = QuestionAnalysis(
        normalized_question="what period was that chart and how many reports",
        route=ResearchRoute.RAG_ONLY,
        required_capabilities=(AgentCapability.DOCUMENTS,),
        chart_requested=False,
        is_follow_up=True,
        reason_codes=(
            "follow_up_about_previous_output",
            "asks_about_covered_period",
            "asks_about_number_of_reports",
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.RAG_ONLY,
            branches=(
                DocumentRetrievalBranch(
                    branch_id="previous_chart_context",
                    request=AdaptiveRetrievalRequest(query="Find the previous chart output"),
                ),
            ),
        ),
    )
    older_artifact = SessionArtifactContext(
        artifact_id="chart:older",
        run_id=uuid.uuid4(),
        user_question="Plot Cloudflare revenue growth.",
        title="Cloudflare revenue growth",
        chart_type="line",
        series_labels=("Cloudflare, Inc. revenue YoY",),
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
        calculations=("year_over_year_growth",),
        period_start=date(2023, 9, 30),
        period_end=date(2026, 3, 31),
        point_count=8,
        source_branch_ids=("cloudflare_revenue",),
    )
    latest_artifact = SessionArtifactContext(
        artifact_id="chart:latest",
        run_id=uuid.uuid4(),
        user_question="а тепер додай туди ще і Apple",
        title="Revenue growth comparison",
        chart_type="line",
        series_labels=(
            "Apple Inc. revenue YoY",
            "Cloudflare, Inc. revenue YoY",
            "Tesla, Inc. revenue YoY",
        ),
        company_ids=(APPLE_ID, COMPANY_ID, NETFLIX_ID),
        metrics=("revenue",),
        calculations=("year_over_year_growth",),
        period_start=date(2024, 3, 31),
        period_end=date(2024, 12, 31),
        point_count=4,
        source_branch_ids=("apple_revenue", "cloudflare_revenue", "tesla_revenue"),
    )
    state = create_initial_agent_state(
        "це був графік за який період? скільки там останніх репортів?",
        session_id="session-previous-chart-period",
    )
    state["session_memory"] = SessionMemory(
        recent_artifacts=(older_artifact, latest_artifact),
    )
    tools = FakeResearchTools()

    result = build_research_graph().invoke(
        state,
        config={"recursion_limit": 24},
        context=ResearchAgentRuntime(model, tools),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["final_answer"] is not None
    assert "2024-03-31" in result["final_answer"]
    assert "2024-12-31" in result["final_answer"]
    assert "2026-03-31" not in result["final_answer"]
    assert "4 точок" in result["final_answer"]
    assert "Apple Inc. revenue YoY" in result["final_answer"]
    assert tools.calls["resolve"] == 0
    assert tools.calls["retrieval"] == 0
    assert model.purposes == [ModelPurpose.PARSE]
    assert result["branch_outcomes"] == ()


def test_sec_item_labels_do_not_trigger_false_abstain() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What is in Cloudflare's report?",
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
                    request=AdaptiveRetrievalRequest(query="Cloudflare annual report"),
                ),
            ),
        ),
        texts=(
            "Коротко по суті: у розділі **Item 1. Business / Overview** Cloudflare "
            "identified competition as a material business risk [document:cloudflare-risk].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Що там з репортом Cloudflare?", session_id="session-sec-item-label"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["repair_attempts"] == 0
    assert result["answer_validation"].valid is True
    assert ModelPurpose.REPAIR not in model.purposes


def test_standalone_multilingual_answer_label_completes_without_false_abstain() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What is in Cloudflare's report?",
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
                    request=AdaptiveRetrievalRequest(query="Cloudflare annual report"),
                ),
            ),
        ),
        texts=(
            "Коротко по суті:\n"
            "Cloudflare identified competition as a material business risk "
            "[document:cloudflare-risk].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Що там з репортом Cloudflare?", session_id="session-standalone-label"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["repair_attempts"] == 0
    assert result["answer_validation"].valid is True
    assert result["claims"][0].text == "Коротко по суті:"
    assert result["claims"][0].material is False
    assert ModelPurpose.REPAIR not in model.purposes


def test_answer_prompt_requires_markdown_headings_and_english_internal_artifacts() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What is in Cloudflare's report?",
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
                    request=AdaptiveRetrievalRequest(query="Cloudflare annual report"),
                ),
            ),
        ),
        texts=("Competition was a reported risk [document:cloudflare-risk].",),
    )

    ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Що там з репортом Cloudflare?", session_id="session-answer-prompt-contract"
    )

    answer_prompt = next(
        messages[0].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.ANSWER
    )
    parse_prompt = next(
        messages[0].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.PARSE
    )
    plan_prompt = next(
        messages[0].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.PLAN
    )
    assert "Use English for all structured fields" in parse_prompt
    assert "Use English for all structured fields" in plan_prompt
    assert "Use English for internal planning" in answer_prompt
    assert "Use Markdown headings for section labels" in answer_prompt
    assert "do not write standalone prose labels ending with ':'" in answer_prompt


def test_repair_prompt_includes_invalid_claim_previews_for_sec_label_answers() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What is in Cloudflare's report?",
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
                    request=AdaptiveRetrievalRequest(query="Cloudflare annual report"),
                ),
            ),
        ),
        texts=(
            "У **Item 1. Business / Overview** Cloudflare identified competition as a "
            "material business risk [invented:evidence].",
            "У **Item 1. Business / Overview** Cloudflare identified competition as a "
            "material business risk [document:cloudflare-risk].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Що там з репортом Cloudflare?", session_id="session-sec-item-label-repair"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["repair_attempts"] == 1
    repair_context = next(
        messages[-1].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.REPAIR
    )
    assert "invalid_claims" in repair_context
    assert "Item 1. Business / Overview" in repair_context


def test_workflow_prepares_unavailable_public_company_before_planning() -> None:
    class OnDemandTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            if self.calls["resolve"] == 1:
                return ResolvedQuery(
                    query=query,
                    entities=(
                        EntityResolution(
                            kind="public_company",
                            mention="netflix",
                            status="unresolved",
                            candidates=(
                                EntityCandidate(
                                    canonical_value="NFLX",
                                    display_value="NETFLIX INC",
                                    match_kind="sec_company_name",
                                ),
                            ),
                        ),
                    ),
                )
            return ResolvedQuery(query=query, company_ids=(COMPANY_ID,))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("Netflix",)
            return (
                public_company_resolution(
                    mention="Netflix",
                    ticker="NFLX",
                    display_name="NETFLIX INC",
                    match_kind="sec_company_extracted",
                ),
            )

        def prepare_companies(
            self,
            *,
            tickers: tuple[str, ...],
            company_ids: tuple[str, ...],
            index_name: str,
            index_version: str,
        ) -> CompanyDataPreparationResult:
            self.calls["prepare"] += 1
            assert tickers == ("NFLX",)
            assert company_ids == ()
            return CompanyDataPreparationResult(
                status="success",
                requested_tickers=tickers,
                skipped_tickers=(),
                prepared_tickers=tickers,
                companies_seen=1,
                filings_seen=1,
                facts_seen=10,
                documents_processed=1,
                chunks_indexed=2,
            )

    analysis = QuestionAnalysis(
        normalized_question="What risks did Netflix report?",
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
                    request=AdaptiveRetrievalRequest(query="Netflix business risks"),
                ),
            ),
        ),
        texts=("Competition was a reported risk [document:cloudflare-risk].",),
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="Netflix"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = OnDemandTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "What risks did Netflix report?", session_id="session-on-demand"
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert tools.calls["prepare"] == 1
    assert tools.calls["resolve"] == 2


def test_follow_up_with_new_public_company_does_not_inherit_previous_company() -> None:
    previous = ResolvedQuery(
        query="Compare Cloudflare revenue growth",
        entities=(
            EntityResolution(
                kind="company",
                mention="cloudflare",
                status="resolved",
                canonical_value=str(COMPANY_ID),
                candidates=(
                    EntityCandidate(
                        id=COMPANY_ID,
                        canonical_value=str(COMPANY_ID),
                        display_value="Cloudflare",
                        match_kind="display_name",
                    ),
                ),
            ),
            EntityResolution(
                kind="financial_metric",
                mention="revenue",
                status="resolved",
                canonical_value="revenue",
                candidates=(
                    EntityCandidate(
                        canonical_value="revenue",
                        display_value="revenue",
                        match_kind="metric_alias",
                    ),
                ),
            ),
        ),
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    current = ResolvedQuery(
        query="а тепер те саме для google",
        entities=(
            EntityResolution(
                kind="public_company",
                mention="google",
                status="unresolved",
                candidates=(
                    EntityCandidate(
                        canonical_value="GOOG",
                        display_value="Alphabet Inc.",
                        match_kind="sec_company_name",
                    ),
                ),
            ),
        ),
    )

    merged = _merge_follow_up_resolution(current, previous)

    assert merged.company_ids == ()
    assert [entity.kind for entity in merged.entities] == [
        "public_company",
        "financial_metric",
    ]
    assert merged.entities[0].candidates[0].canonical_value == "GOOG"
    assert merged.metrics == ("revenue",)


def test_resolve_entities_extracts_follow_up_public_company_target() -> None:
    class CompanylessTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("Zoom",)
            return (
                public_company_resolution(
                    mention="Zoom",
                    ticker="ZM",
                    display_name="Zoom Communications Inc.",
                    match_kind="sec_company_extracted",
                ),
            )

    analysis = QuestionAnalysis(
        normalized_question="Compare Zoom revenue growth over the last eight quarters.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION),
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="Zoom"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = CompanylessTools()
    state = create_initial_agent_state(
        "а тепер те саме для Zoom",
        session_id="session-follow-up-zoom",
    )
    state["analysis"] = analysis
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        ),
        last_execution_plan=ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=(
                CalculationBranch(
                    branch_id="revenue_qoq_growth",
                    operation="quarter_over_quarter_growth",
                    input_refs=("source_revenue_quarters",),
                    window=8,
                ),
            ),
        ),
    )

    update = _resolve_entities(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    resolved = cast(ResolvedQuery, update["resolved_query"])
    frame = cast(ResearchFrame, update["research_frame"])
    public_company = next(entity for entity in resolved.entities if entity.kind == "public_company")
    assert resolved.company_ids == ()
    assert public_company.mention == "Zoom"
    assert public_company.candidates[0].canonical_value == "ZM"
    assert frame.company_targets[0].mention == "Zoom"
    assert frame.company_targets[0].ticker == "ZM"
    assert frame.follow_up_operation == "quarter_over_quarter_growth"
    assert frame.follow_up_window == 8
    assert tools.calls["resolve_public_company_mentions"] == 1
    assert ModelPurpose.ENTITY_EXTRACTION in model.purposes


def test_resolve_entities_does_not_inherit_previous_company_for_unknown_extracted_target() -> None:
    class CompanylessTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

    analysis = QuestionAnalysis(
        normalized_question="now do the same for Globex",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION),
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="Globex"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = CompanylessTools()
    state = create_initial_agent_state(
        "а тепер те саме для Globex",
        session_id="session-follow-up-unknown-company",
    )
    state["analysis"] = analysis
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        )
    )

    update = _resolve_entities(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    resolved = cast(ResolvedQuery, update["resolved_query"])
    public_company = next(entity for entity in resolved.entities if entity.kind == "public_company")
    assert resolved.company_ids == ()
    assert public_company.mention == "Globex"
    assert public_company.candidates == ()
    assert tools.calls["resolve_public_company_mentions"] == 1


def test_resolve_entities_does_not_inherit_previous_company_for_ambiguous_target() -> None:
    class AmbiguousCompanyTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("Acme",)
            return (
                EntityResolution(
                    kind="public_company",
                    mention="Acme",
                    status="ambiguous",
                    candidates=(
                        EntityCandidate(
                            canonical_value="ACMA",
                            display_value="Acme Holdings Inc.",
                            match_kind="sec_company_extracted",
                        ),
                        EntityCandidate(
                            canonical_value="ACMB",
                            display_value="Acme Software Inc.",
                            match_kind="sec_company_extracted",
                        ),
                    ),
                ),
            )

    analysis = QuestionAnalysis(
        normalized_question="now do the same for Acme",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION),
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="Acme"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = AmbiguousCompanyTools()
    state = create_initial_agent_state(
        "а тепер те саме для Acme",
        session_id="session-follow-up-ambiguous-company",
    )
    state["analysis"] = analysis
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        )
    )

    update = _resolve_entities(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    resolved = cast(ResolvedQuery, update["resolved_query"])
    public_company = next(entity for entity in resolved.entities if entity.kind == "public_company")
    assert resolved.company_ids == ()
    assert public_company.mention == "Acme"
    assert public_company.status == "ambiguous"
    assert [candidate.canonical_value for candidate in public_company.candidates] == [
        "ACMA",
        "ACMB",
    ]
    assert tools.calls["resolve_public_company_mentions"] == 1


def test_ambiguous_company_follow_up_asks_for_clarification_before_planning() -> None:
    class AmbiguousUnitedTools(FakeResearchTools):
        def resolve_non_company_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve_non_company"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("United",)
            return (
                EntityResolution(
                    kind="public_company",
                    mention="United",
                    status="ambiguous",
                    candidates=(
                        EntityCandidate(
                            canonical_value="UAL",
                            display_value="United Airlines Holdings Inc.",
                            match_kind="sec_company_extracted",
                        ),
                        EntityCandidate(
                            canonical_value="BNO",
                            display_value="United States Brent Oil Fund LP",
                            match_kind="sec_company_extracted",
                        ),
                    ),
                ),
            )

        def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
            raise AssertionError("ambiguous company should not reach financial facts")

    analysis = QuestionAnalysis(
        normalized_question="now do the same for United",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION),
        company_extraction=CompanyMentionExtraction(
            companies=(
                CompanyMentionCandidate(
                    mention="United Acquisition Corp. I",
                    ticker="UAC",
                    legal_name="United Acquisition Corp. I",
                ),
            ),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = AmbiguousUnitedTools()
    state = create_initial_agent_state(
        "Now do the same for United",
        session_id="session-follow-up-united-clarification",
    )
    state["analysis"] = analysis
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        )
    )

    resolve_update = _resolve_entities(state, Runtime(context=ResearchAgentRuntime(model, tools)))
    state.update(resolve_update)
    prepare_update = _prepare_company_data(
        state,
        Runtime(context=ResearchAgentRuntime(model, tools)),
    )
    state.update(prepare_update)
    plan_update = _plan_request(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    resolved = cast(ResolvedQuery, state["resolved_query"])
    answer = cast(str, plan_update["draft_answer"])
    assert plan_update["status"] is AgentRunStatus.ABSTAINED
    assert any(error.code == "ambiguous_company" for error in plan_update["errors"])
    assert resolved.company_ids == ()
    assert "Please clarify which company" in answer
    assert "United Airlines Holdings Inc. (UAL)" in answer
    assert "United States Brent Oil Fund LP (BNO)" in answer
    assert ModelPurpose.PLAN not in model.purposes
    assert tools.calls["prepare"] == 0
    assert tools.calls["financial"] == 0


def test_chart_type_follow_up_does_not_treat_bar_as_company() -> None:
    class BarTickerTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            return ResolvedQuery(
                query=query,
                entities=(
                    public_company_resolution(
                        mention="bar",
                        ticker="BAR",
                        display_name="GraniteShares Gold Trust",
                        match_kind="sec_company_ticker",
                    ),
                ),
                metrics=("revenue",),
            )

    analysis = QuestionAnalysis(
        normalized_question="build a bar chart from the same data",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=(
            "explicit_chart_request",
            "follow_up_on_prior_table",
            "derived_comparison",
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.HYBRID),
        company_extraction=CompanyMentionExtraction(
            companies=(),
            reason_codes=("no_company_mentioned", "bar_is_chart_type"),
        ),
    )
    tools = BarTickerTools()
    state = create_initial_agent_state(
        "а тепер побудуй bar chart на цих данних",
        session_id="session-follow-up-bar-chart",
    )
    state["analysis"] = analysis
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        )
    )

    update = _resolve_entities(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    resolved = cast(ResolvedQuery, update["resolved_query"])
    assert resolved.company_ids == (COMPANY_ID,)
    assert all(entity.mention != "bar" for entity in resolved.entities)
    assert all(
        not (entity.candidates and entity.candidates[0].display_value == "GraniteShares Gold Trust")
        for entity in resolved.entities
    )
    assert tools.calls["resolve_public_company_mentions"] == 0
    assert ModelPurpose.ENTITY_EXTRACTION in model.purposes


def test_failed_turn_does_not_promote_bad_company_resolution_to_session_memory() -> None:
    previous = ResolvedQuery(
        query="Compare Cloudflare revenue growth",
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    bad_bar_resolution = ResolvedQuery(
        query="а тепер побудуй bar chart на цих данних",
        entities=(
            EntityResolution(
                kind="company",
                mention="bar",
                status="resolved",
                canonical_value=str(APPLE_ID),
                candidates=(
                    EntityCandidate(
                        id=APPLE_ID,
                        canonical_value=str(APPLE_ID),
                        display_value="GraniteShares Gold Trust",
                        match_kind="ticker",
                    ),
                ),
            ),
            public_company_resolution(
                mention="bar",
                ticker="BAR",
                display_name="GraniteShares Gold Trust",
                match_kind="sec_company_ticker",
            ),
        ),
        company_ids=(APPLE_ID,),
        metrics=("revenue",),
    )
    state = create_initial_agent_state(
        "а тепер побудуй bar chart на цих данних",
        session_id="session-failed-memory-promotion",
    )
    state["status"] = AgentRunStatus.FAILED
    state["resolved_query"] = bad_bar_resolution
    state["session_memory"] = SessionMemory(
        last_resolved_query=previous,
        recent_resolved_queries=(previous,),
    )

    memory = _updated_session_memory(
        state,
        cache_limit=20,
        promote_current_context=False,
    )

    assert memory.last_resolved_query == previous
    assert memory.recent_resolved_queries == (previous,)
    assert all(
        entity.mention != "bar"
        for query in memory.recent_resolved_queries
        for entity in query.entities
    )


def test_add_company_bar_chart_follow_up_prepares_ticker_without_unresolved_duplicate() -> None:
    class AddAmazonTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            if query == "AMZN":
                return ResolvedQuery(
                    query=query,
                    entities=(
                        EntityResolution(
                            kind="company",
                            mention="amzn",
                            status="resolved",
                            canonical_value=str(AMAZON_ID),
                            candidates=(
                                EntityCandidate(
                                    id=AMAZON_ID,
                                    canonical_value=str(AMAZON_ID),
                                    display_value="AMAZON COM INC",
                                    match_kind="ticker",
                                ),
                            ),
                        ),
                        public_company_resolution(
                            mention="amzn",
                            ticker="AMZN",
                            display_name="AMAZON COM INC",
                            match_kind="sec_company_ticker",
                        ),
                    ),
                    company_ids=(AMAZON_ID,),
                    metrics=("revenue",),
                )
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_non_company_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve_non_company"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("amazon",)
            return (
                public_company_resolution(
                    mention="amazon",
                    ticker="AMZN",
                    display_name="AMAZON COM INC",
                    match_kind="sec_company_extracted",
                ),
            )

        def prepare_companies(
            self,
            *,
            tickers: tuple[str, ...],
            company_ids: tuple[str, ...],
            index_name: str,
            index_version: str,
        ) -> CompanyDataPreparationResult:
            self.calls["prepare"] += 1
            assert tickers == ("AMZN",)
            assert company_ids == (str(MICROSOFT_ID),)
            return CompanyDataPreparationResult(
                status="success",
                requested_tickers=tickers,
                skipped_tickers=(),
                prepared_tickers=tickers,
                companies_seen=1,
                filings_seen=2,
                facts_seen=8,
                documents_processed=2,
                chunks_indexed=4,
            )

        def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
            self.calls["financial"] += 1
            assert request.metrics == ("revenue",)
            company_id = request.company_ids[0]
            company_name = "AMAZON COM INC" if company_id == AMAZON_ID else "MICROSOFT CORP"
            ticker = "AMZN" if company_id == AMAZON_ID else "MSFT"
            return FinancialFactQueryResult(
                query=request,
                observations=(
                    _financial_observation(date(2025, 9, 30), Decimal("100")).model_copy(
                        update={
                            "id": uuid.uuid5(uuid.NAMESPACE_DNS, f"{company_id}-2025-q3"),
                            "company_id": company_id,
                            "company_name": company_name,
                            "ticker": ticker,
                            "period_type": "quarter",
                            "fiscal_period": "Q3",
                        }
                    ),
                    _financial_observation(date(2026, 3, 31), Decimal("125")).model_copy(
                        update={
                            "id": uuid.uuid5(uuid.NAMESPACE_DNS, f"{company_id}-2026-q1"),
                            "company_id": company_id,
                            "company_name": company_name,
                            "ticker": ticker,
                            "period_type": "quarter",
                            "fiscal_period": "Q1",
                        }
                    ),
                ),
                available_units=("USD",),
            )

    analysis = QuestionAnalysis(
        normalized_question=(
            "Compare Microsoft and Amazon revenue growth over the last eight quarters "
            "and build a bar chart."
        ),
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=(
            "follow_up_request",
            "adds_company",
            "explicit_chart_request",
            "requires_growth_calculation",
        ),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            FinancialFactsBranch(
                branch_id="microsoft_revenue",
                request=FinancialFactQuery(
                    company_ids=(MICROSOFT_ID,),
                    metrics=("revenue",),
                ),
            ),
            CalculationBranch(
                branch_id="microsoft_growth",
                operation="quarter_over_quarter_growth",
                input_refs=("microsoft_revenue",),
                depends_on=("microsoft_revenue",),
            ),
            FinancialFactsBranch(
                branch_id="amazon_revenue",
                request=FinancialFactQuery(
                    company_ids=(AMAZON_ID,),
                    metrics=("revenue",),
                ),
            ),
            CalculationBranch(
                branch_id="amazon_growth",
                operation="quarter_over_quarter_growth",
                input_refs=("amazon_revenue",),
                depends_on=("amazon_revenue",),
            ),
            ChartBranch(
                branch_id="growth_chart",
                chart_type="bar",
                dataset_ref="microsoft_growth",
                depends_on=("microsoft_growth", "amazon_growth"),
                title="Microsoft and Amazon revenue growth",
            ),
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="amazon"),),
            reason_codes=("explicit_added_company",),
        ),
    )
    tools = AddAmazonTools()
    microsoft = ResolvedQuery(
        query="а тепер зроби те саме для microsoft",
        entities=(
            EntityResolution(
                kind="company",
                mention="msft",
                status="resolved",
                canonical_value=str(MICROSOFT_ID),
                candidates=(
                    EntityCandidate(
                        id=MICROSOFT_ID,
                        canonical_value=str(MICROSOFT_ID),
                        display_value="MICROSOFT CORP",
                        match_kind="ticker",
                    ),
                ),
            ),
        ),
        company_ids=(MICROSOFT_ID,),
        metrics=("revenue",),
    )
    state = create_initial_agent_state(
        "а тепер додай amazon і побудуй bar chart",
        session_id="session-add-amazon-bar-chart",
    )
    state["analysis"] = analysis
    state["session_memory"] = SessionMemory(
        last_resolved_query=microsoft,
        recent_resolved_queries=(microsoft,),
    )

    resolve_update = _resolve_entities(state, Runtime(context=ResearchAgentRuntime(model, tools)))
    state.update(resolve_update)
    prepare_update = _prepare_company_data(
        state,
        Runtime(context=ResearchAgentRuntime(model, tools)),
    )
    state.update(prepare_update)

    resolved = cast(ResolvedQuery, state["resolved_query"])
    frame = cast(ResearchFrame, state["research_frame"])
    assert resolved.company_ids == (MICROSOFT_ID, AMAZON_ID)
    assert not any(
        entity.kind == "public_company"
        and entity.candidates
        and entity.candidates[0].canonical_value == "AMZN"
        for entity in resolved.entities
    )
    assert [target.company_id for target in frame.company_targets] == [
        AMAZON_ID,
        MICROSOFT_ID,
    ]
    assert all(target.status == "resolved" for target in frame.company_targets)

    plan_update = _plan_request(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    assert "errors" not in plan_update
    execution_plan = cast(ExecutionPlan, plan_update["execution_plan"])
    assert execution_plan.branches[-1].kind == "generate_chart_spec"
    assert tools.calls["prepare"] == 1
    assert tools.calls["resolve_public_company_mentions"] == 2


def test_prepared_follow_up_company_resolves_company_id_from_extracted_ticker() -> None:
    class PreparedZoomTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            if query == "ZM":
                return ResolvedQuery(
                    query=query,
                    entities=(
                        EntityResolution(
                            kind="company",
                            mention="zm",
                            status="resolved",
                            canonical_value=str(ZOOM_ID),
                            candidates=(
                                EntityCandidate(
                                    id=ZOOM_ID,
                                    canonical_value=str(ZOOM_ID),
                                    display_value="Zoom Communications, Inc.",
                                    match_kind="ticker",
                                ),
                            ),
                        ),
                    ),
                    company_ids=(ZOOM_ID,),
                    metrics=("revenue",),
                )
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("Zoom",)
            return (
                public_company_resolution(
                    mention="Zoom",
                    ticker="ZM",
                    display_name="Zoom Communications, Inc.",
                    match_kind="sec_company_extracted",
                ),
            )

        def prepare_companies(
            self,
            *,
            tickers: tuple[str, ...],
            company_ids: tuple[str, ...],
            index_name: str,
            index_version: str,
        ) -> CompanyDataPreparationResult:
            self.calls["prepare"] += 1
            assert tickers == ("ZM",)
            assert company_ids == ()
            return CompanyDataPreparationResult(
                status="success",
                requested_tickers=tickers,
                skipped_tickers=(),
                prepared_tickers=tickers,
                companies_seen=1,
                filings_seen=1,
                facts_seen=8,
                documents_processed=1,
                chunks_indexed=2,
            )

        def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
            self.calls["financial"] += 1
            assert request.company_ids == (ZOOM_ID,)
            observations = (
                _financial_observation(date(2025, 9, 30), Decimal("120")).model_copy(
                    update={
                        "id": uuid.uuid5(uuid.NAMESPACE_DNS, "zoom-2025-q3"),
                        "company_id": ZOOM_ID,
                        "company_name": "Zoom Communications, Inc.",
                        "ticker": "ZM",
                        "period_start": date(2025, 7, 1),
                        "period_type": "quarter",
                        "fiscal_period": "Q3",
                    }
                ),
                _financial_observation(date(2025, 12, 31), Decimal("132")).model_copy(
                    update={
                        "id": uuid.uuid5(uuid.NAMESPACE_DNS, "zoom-2025-q4"),
                        "company_id": ZOOM_ID,
                        "company_name": "Zoom Communications, Inc.",
                        "ticker": "ZM",
                        "period_start": date(2025, 10, 1),
                        "period_type": "quarter",
                        "fiscal_period": "Q4",
                    }
                ),
            )
            return FinancialFactQueryResult(
                query=request,
                observations=observations,
                available_units=("USD",),
            )

    analysis = QuestionAnalysis(
        normalized_question="now do the same for Zoom",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
        reason_codes=("follow_up", "revenue_growth_requested"),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=(
                FinancialFactsBranch(
                    branch_id="source_revenue_quarters",
                    request=FinancialFactQuery(metrics=("revenue",), limit=8),
                ),
                CalculationBranch(
                    branch_id="revenue_qoq_growth",
                    operation="quarter_over_quarter_growth",
                    input_refs=("source_revenue_quarters",),
                    window=8,
                ),
            ),
        ),
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="Zoom"),),
            reason_codes=("explicit_company_target",),
        ),
        texts=("Zoom revenue grew 10% quarter over quarter [calculation:revenue_qoq_growth].",),
    )
    tools = PreparedZoomTools()
    state = create_initial_agent_state(
        "а тепер те саме для Zoom",
        session_id="session-follow-up-prepared-zoom",
    )
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        )
    )

    result = build_research_graph().invoke(
        state,
        config={"recursion_limit": 24},
        context=ResearchAgentRuntime(model, tools),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["resolved_query"].company_ids == (ZOOM_ID,)
    assert tools.calls["prepare"] == 1
    assert tools.calls["financial"] == 2


def test_ready_follow_up_ticker_resolves_company_id_from_skipped_prepare() -> None:
    class ReadyZoomTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            if query == "ZM":
                return ResolvedQuery(
                    query=query,
                    entities=(
                        EntityResolution(
                            kind="company",
                            mention="zm",
                            status="resolved",
                            canonical_value=str(ZOOM_ID),
                            candidates=(
                                EntityCandidate(
                                    id=ZOOM_ID,
                                    canonical_value=str(ZOOM_ID),
                                    display_value="Zoom Communications, Inc.",
                                    match_kind="ticker",
                                ),
                            ),
                        ),
                    ),
                    company_ids=(ZOOM_ID,),
                    metrics=("revenue",),
                )
            return ResolvedQuery(query=query, metrics=("revenue",))

        def resolve_public_company_mentions(
            self,
            candidates: Sequence[CompanyMentionCandidate],
        ) -> tuple[EntityResolution, ...]:
            self.calls["resolve_public_company_mentions"] += 1
            assert tuple(candidate.mention for candidate in candidates) == ("Zoom",)
            return (
                public_company_resolution(
                    mention="Zoom",
                    ticker="ZM",
                    display_name="Zoom Communications, Inc.",
                    match_kind="sec_company_extracted",
                ),
            )

        def prepare_companies(
            self,
            *,
            tickers: tuple[str, ...],
            company_ids: tuple[str, ...],
            index_name: str,
            index_version: str,
        ) -> CompanyDataPreparationResult:
            self.calls["prepare"] += 1
            assert tickers == ("ZM",)
            assert company_ids == ()
            return CompanyDataPreparationResult(
                status="skipped",
                requested_tickers=tickers,
                skipped_tickers=tickers,
                prepared_tickers=(),
            )

    analysis = QuestionAnalysis(
        normalized_question="Compare Zoom revenue growth over the last eight quarters.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION),
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="Zoom"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = ReadyZoomTools()
    state = create_initial_agent_state(
        "а тепер те саме для Zoom",
        session_id="session-follow-up-ready-zoom",
    )
    state["analysis"] = analysis
    state["resolved_query"] = ResolvedQuery(
        query="а тепер те саме для Zoom",
        entities=(
            public_company_resolution(
                mention="Zoom",
                ticker="ZM",
                display_name="Zoom Communications, Inc.",
                match_kind="sec_company_extracted",
            ),
        ),
        metrics=("revenue",),
    )
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        )
    )

    update = _prepare_company_data(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    resolved = cast(ResolvedQuery, update["resolved_query"])
    frame = cast(ResearchFrame, update["research_frame"])
    assert resolved.company_ids == (ZOOM_ID,)
    assert frame.company_targets[0].company_id == ZOOM_ID
    assert frame.company_targets[0].source == "current_question"
    assert not frame.inherited_from_previous
    assert tools.calls["prepare"] == 1
    assert tools.calls["resolve_public_company_mentions"] == 1


def test_plan_request_abstains_before_planning_when_follow_up_financial_data_missing() -> None:
    class MissingFinancialFactsTools(FakeResearchTools):
        def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
            self.calls["financial"] += 1
            assert request.company_ids == (NOKIA_ID,)
            assert request.metrics == ("revenue",)
            return FinancialFactQueryResult(
                query=request,
                observations=(),
                available_units=(),
                warnings=("no_matching_financial_facts",),
            )

    analysis = QuestionAnalysis(
        normalized_question="now do the same for Nokia",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
        reason_codes=("follow_up", "revenue_growth_requested"),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=(
                FinancialFactsBranch(
                    branch_id="source_revenue_quarters",
                    request=FinancialFactQuery(metrics=("revenue",), limit=8),
                ),
                CalculationBranch(
                    branch_id="revenue_qoq_growth",
                    operation="quarter_over_quarter_growth",
                    input_refs=("source_revenue_quarters",),
                    window=8,
                ),
            ),
        ),
    )
    state = create_initial_agent_state(
        "а тепер те саме для Nokia",
        session_id="session-follow-up-nokia-missing-readiness",
    )
    state["analysis"] = analysis
    state["resolved_query"] = ResolvedQuery(
        query="а тепер те саме для Nokia",
        entities=(
            EntityResolution(
                kind="company",
                mention="nokia",
                status="resolved",
                canonical_value=str(NOKIA_ID),
                candidates=(
                    EntityCandidate(
                        id=NOKIA_ID,
                        canonical_value=str(NOKIA_ID),
                        display_value="NOKIA CORP",
                        match_kind="normalized_legal_name",
                    ),
                ),
            ),
        ),
        company_ids=(NOKIA_ID,),
        metrics=("revenue",),
    )
    state["session_memory"] = SessionMemory(
        last_resolved_query=ResolvedQuery(
            query="Compare Cloudflare revenue growth",
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
        ),
        last_execution_plan=ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=(
                CalculationBranch(
                    branch_id="revenue_qoq_growth",
                    operation="quarter_over_quarter_growth",
                    input_refs=("source_revenue_quarters",),
                    window=8,
                ),
            ),
        ),
    )
    tools = MissingFinancialFactsTools()

    update = _plan_request(state, Runtime(context=ResearchAgentRuntime(model, tools)))

    frame = cast(ResearchFrame, update["research_frame"])
    assert update["status"] is AgentRunStatus.ABSTAINED
    assert update["draft_answer"] is not None
    assert "NOKIA CORP" in cast(str, update["draft_answer"])
    assert frame.financial_readiness[0].status == "missing"
    assert frame.financial_readiness[0].warnings == ("no_matching_financial_facts",)
    assert tools.calls["financial"] == 1
    assert ModelPurpose.PLAN not in model.purposes


def test_follow_up_without_company_mention_still_inherits_previous_company() -> None:
    previous = ResolvedQuery(
        query="Compare Cloudflare revenue growth",
        entities=(
            EntityResolution(
                kind="company",
                mention="cloudflare",
                status="resolved",
                canonical_value=str(COMPANY_ID),
                candidates=(
                    EntityCandidate(
                        id=COMPANY_ID,
                        canonical_value=str(COMPANY_ID),
                        display_value="Cloudflare",
                        match_kind="display_name",
                    ),
                ),
            ),
        ),
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    current = ResolvedQuery(query="do the same", fiscal_years=(2025,))

    merged = _merge_follow_up_resolution(current, previous)

    assert merged.company_ids == (COMPANY_ID,)
    assert [entity.kind for entity in merged.entities] == ["company"]
    assert merged.metrics == ("revenue",)
    assert merged.fiscal_years == (2025,)


def test_plural_company_follow_up_inherits_recent_company_set() -> None:
    cloudflare = ResolvedQuery(
        query="Compare Cloudflare revenue growth",
        entities=(
            EntityResolution(
                kind="company",
                mention="cloudflare",
                status="resolved",
                canonical_value=str(COMPANY_ID),
                candidates=(
                    EntityCandidate(
                        id=COMPANY_ID,
                        canonical_value=str(COMPANY_ID),
                        display_value="Cloudflare",
                        match_kind="display_name",
                    ),
                ),
            ),
            EntityResolution(
                kind="financial_metric",
                mention="revenue",
                status="resolved",
                canonical_value="revenue",
                candidates=(
                    EntityCandidate(
                        canonical_value="revenue",
                        display_value="revenue",
                        match_kind="metric_alias",
                    ),
                ),
            ),
        ),
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    google = ResolvedQuery(
        query="зроби те саме для google",
        entities=(
            EntityResolution(
                kind="company",
                mention="google",
                status="resolved",
                canonical_value=str(NETFLIX_ID),
                candidates=(
                    EntityCandidate(
                        id=NETFLIX_ID,
                        canonical_value=str(NETFLIX_ID),
                        display_value="Alphabet Inc.",
                        match_kind="sec_company_name",
                    ),
                ),
            ),
        ),
        company_ids=(NETFLIX_ID,),
        metrics=("revenue",),
    )
    current = ResolvedQuery(query="тепер порівняй ці компанії на графіку")
    analysis = QuestionAnalysis(
        normalized_question=(
            "compare Cloudflare and Alphabet on a chart using their revenue growth "
            "over the last eight quarters"
        ),
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("comparison_requested", "chart_explicitly_requested"),
    )
    memory = SessionMemory(
        last_resolved_query=google,
        recent_resolved_queries=(cloudflare, google),
    )

    merged = _merge_follow_up_if_needed(current, analysis, memory)

    assert merged.company_ids == (COMPANY_ID, NETFLIX_ID)
    assert [entity.mention for entity in merged.entities if entity.kind == "company"] == [
        "cloudflare",
        "google",
    ]
    assert merged.metrics == ("revenue",)


def test_add_series_follow_up_merges_new_company_with_previous_chart_companies() -> None:
    cloudflare = ResolvedQuery(
        query="Plot Cloudflare revenue growth against the federal funds rate.",
        entities=(
            EntityResolution(
                kind="company",
                mention="cloudflare",
                status="resolved",
                canonical_value=str(COMPANY_ID),
                candidates=(
                    EntityCandidate(
                        id=COMPANY_ID,
                        canonical_value=str(COMPANY_ID),
                        display_value="Cloudflare",
                        match_kind="display_name",
                    ),
                ),
            ),
            EntityResolution(
                kind="financial_metric",
                mention="revenue",
                status="resolved",
                canonical_value="revenue",
                candidates=(
                    EntityCandidate(
                        canonical_value="revenue",
                        display_value="revenue",
                        match_kind="metric_alias",
                    ),
                ),
            ),
        ),
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    tesla = ResolvedQuery(
        query="а тепер на графік виведи обидва",
        entities=(
            EntityResolution(
                kind="company",
                mention="tesla",
                status="resolved",
                canonical_value=str(NETFLIX_ID),
                candidates=(
                    EntityCandidate(
                        id=NETFLIX_ID,
                        canonical_value=str(NETFLIX_ID),
                        display_value="Tesla, Inc.",
                        match_kind="normalized_legal_name",
                    ),
                ),
            ),
        ),
        company_ids=(NETFLIX_ID, COMPANY_ID),
        metrics=("revenue",),
    )
    apple = ResolvedQuery(
        query="а тепер додай туди ще і Apple",
        entities=(
            EntityResolution(
                kind="company",
                mention="apple",
                status="resolved",
                canonical_value=str(APPLE_ID),
                candidates=(
                    EntityCandidate(
                        id=APPLE_ID,
                        canonical_value=str(APPLE_ID),
                        display_value="Apple Inc.",
                        match_kind="normalized_legal_name",
                    ),
                ),
            ),
        ),
        company_ids=(APPLE_ID,),
        metrics=("revenue",),
    )
    analysis = QuestionAnalysis(
        normalized_question="add Apple to the existing comparison chart",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "add_series", "comparison_chart"),
    )
    memory = SessionMemory(
        last_resolved_query=tesla,
        recent_resolved_queries=(cloudflare, tesla),
    )

    merged = _merge_follow_up_if_needed(apple, analysis, memory)

    assert merged.company_ids == (COMPANY_ID, NETFLIX_ID, APPLE_ID)
    assert [entity.mention for entity in merged.entities if entity.kind == "company"] == [
        "apple",
        "cloudflare",
        "tesla",
    ]
    assert merged.metrics == ("revenue",)


def test_add_series_follow_up_uses_legacy_last_resolved_query_memory() -> None:
    cloudflare = ResolvedQuery(
        query="Compare Cloudflare revenue growth",
        entities=(
            EntityResolution(
                kind="company",
                mention="cloudflare",
                status="resolved",
                canonical_value=str(COMPANY_ID),
                candidates=(
                    EntityCandidate(
                        id=COMPANY_ID,
                        canonical_value=str(COMPANY_ID),
                        display_value="Cloudflare",
                        match_kind="display_name",
                    ),
                ),
            ),
        ),
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    amazon = ResolvedQuery(
        query="add Amazon to that chart",
        entities=(
            EntityResolution(
                kind="company",
                mention="amazon",
                status="resolved",
                canonical_value=str(AMAZON_ID),
                candidates=(
                    EntityCandidate(
                        id=AMAZON_ID,
                        canonical_value=str(AMAZON_ID),
                        display_value="Amazon.com, Inc.",
                        match_kind="normalized_legal_name",
                    ),
                ),
            ),
        ),
        company_ids=(AMAZON_ID,),
    )
    analysis = QuestionAnalysis(
        normalized_question="add Amazon to the existing comparison chart",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "add_series", "comparison_chart"),
    )
    memory = SessionMemory(last_resolved_query=cloudflare)

    merged = _merge_follow_up_if_needed(amazon, analysis, memory)

    assert merged.company_ids == (COMPANY_ID, AMAZON_ID)
    assert [entity.mention for entity in merged.entities if entity.kind == "company"] == [
        "amazon",
        "cloudflare",
    ]
    assert merged.metrics == ("revenue",)


def test_add_series_follow_up_plan_accepts_previous_and_new_company_ids() -> None:
    analysis = QuestionAnalysis(
        normalized_question="add Apple to the existing comparison chart",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "add_series", "comparison_chart"),
    )
    cloudflare = ResolvedQuery(
        query="Plot Cloudflare revenue growth.",
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    previous_chart = ResolvedQuery(
        query="а тепер на графік виведи обидва",
        company_ids=(NETFLIX_ID, COMPANY_ID),
        metrics=("revenue",),
    )
    apple = ResolvedQuery(
        query="а тепер додай туди ще і Apple",
        entities=(
            EntityResolution(
                kind="company",
                mention="apple",
                status="resolved",
                canonical_value=str(APPLE_ID),
            ),
        ),
        company_ids=(APPLE_ID,),
        metrics=("revenue",),
    )
    memory = SessionMemory(
        last_resolved_query=previous_chart,
        recent_resolved_queries=(cloudflare, previous_chart),
    )
    merged = _merge_follow_up_if_needed(apple, analysis, memory)
    branches: list[FinancialFactsBranch | CalculationBranch | ChartBranch] = []
    growth_refs: list[str] = []
    for index, company_id in enumerate(merged.company_ids, start=1):
        facts_id = f"company_{index}_revenue"
        growth_id = f"company_{index}_growth"
        branches.append(
            FinancialFactsBranch(
                branch_id=facts_id,
                request=FinancialFactQuery(
                    company_ids=(company_id,),
                    metrics=("revenue",),
                ),
            )
        )
        branches.append(
            CalculationBranch(
                branch_id=growth_id,
                operation="year_over_year_growth",
                input_refs=(facts_id,),
                depends_on=(facts_id,),
            )
        )
        growth_refs.append(growth_id)
    branches.append(
        ChartBranch(
            branch_id="comparison_chart",
            chart_type="line",
            dataset_ref=growth_refs[0],
            depends_on=tuple(growth_refs),
            title="Revenue growth comparison",
        )
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION, branches=tuple(branches)),
    )
    state = create_initial_agent_state(
        "а тепер додай туди ще і Apple",
        session_id="session-add-series-plan-validation",
    )
    state["analysis"] = analysis
    state["resolved_query"] = merged
    state["session_memory"] = memory

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    plan = update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    assert "errors" not in update
    planned_company_ids = [
        branch.request.company_ids
        for branch in plan.branches
        if isinstance(branch, FinancialFactsBranch)
    ]
    assert planned_company_ids == [
        (COMPANY_ID,),
        (NETFLIX_ID,),
        (APPLE_ID,),
    ]


def test_planner_receives_recent_artifact_timeline_context() -> None:
    analysis = QuestionAnalysis(
        normalized_question="build the same chart again",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "same_chart"),
    )
    facts = FinancialFactsBranch(
        branch_id="revenue",
        request=FinancialFactQuery(
            company_ids=(COMPANY_ID,),
            metrics=("revenue",),
            fiscal_years=(2023, 2024, 2025),
        ),
    )
    growth = CalculationBranch(
        branch_id="growth",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    chart = ChartBranch(
        branch_id="chart",
        chart_type="line",
        dataset_ref=growth.branch_id,
        depends_on=(growth.branch_id,),
        title="Revenue growth",
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION, branches=(facts, growth, chart)),
    )
    state = create_initial_agent_state(
        "побудуй такий графік ще раз",
        session_id="session-artifact-planner-context",
    )
    state["analysis"] = analysis
    state["resolved_query"] = ResolvedQuery(
        query="побудуй такий графік ще раз",
        company_ids=(COMPANY_ID,),
        metrics=("revenue",),
    )
    state["session_memory"] = SessionMemory(
        recent_artifacts=(
            SessionArtifactContext(
                artifact_id="chart:first",
                run_id=uuid.uuid4(),
                user_question="Plot Cloudflare revenue growth.",
                title="Revenue growth",
                chart_type="line",
                series_labels=("Cloudflare revenue YoY",),
                company_ids=(COMPANY_ID,),
                metrics=("revenue",),
                calculations=("year_over_year_growth",),
                period_start=date(2023, 9, 30),
                period_end=date(2026, 3, 31),
                point_count=8,
                source_branch_ids=("revenue",),
            ),
            SessionArtifactContext(
                artifact_id="chart:second",
                run_id=uuid.uuid4(),
                user_question="Add Tesla.",
                title="Peer revenue growth",
                chart_type="line",
                series_labels=("Cloudflare revenue YoY", "Tesla revenue YoY"),
                company_ids=(COMPANY_ID, NETFLIX_ID),
                metrics=("revenue",),
                calculations=("year_over_year_growth",),
                period_start=date(2024, 9, 30),
                period_end=date(2026, 3, 31),
                point_count=5,
                source_branch_ids=("cloudflare_revenue", "tesla_revenue"),
            ),
        )
    )

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert "execution_plan" in update
    plan_messages = next(
        messages for purpose, messages in model.model_calls if purpose is ModelPurpose.PLAN
    )
    context = json.loads(plan_messages[1].content)
    assert context["research_frame"]["company_targets"][0]["company_id"] == str(COMPANY_ID)
    assert context["research_frame"]["financial_readiness"][0]["status"] == "available"
    assert [artifact["artifact_id"] for artifact in context["recent_artifacts"]] == [
        "chart:first",
        "chart:second",
    ]
    assert context["recent_artifacts"][1]["period"] == {
        "start": "2024-09-30",
        "end": "2026-03-31",
        "point_count": 5,
    }
    assert context["recent_artifacts"][1]["series_labels"] == [
        "Cloudflare revenue YoY",
        "Tesla revenue YoY",
    ]


def test_period_override_follow_up_reuses_recent_chart_artifact_without_model_plan() -> None:
    analysis = QuestionAnalysis(
        normalized_question="побудуй такий графік за період 2023-2025",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "change_period", "same_chart"),
    )
    artifact = SessionArtifactContext(
        artifact_id="chart:peer_growth",
        run_id=uuid.uuid4(),
        user_question="а тепер додай туди ще і Apple",
        title="Apple vs Cloudflare vs Tesla Revenue Growth",
        chart_type="line",
        series_labels=(
            "Apple Inc. revenue YoY",
            "Cloudflare, Inc. revenue YoY",
            "Tesla, Inc. revenue YoY",
        ),
        company_ids=(APPLE_ID, COMPANY_ID, NETFLIX_ID),
        metrics=("revenue",),
        calculations=("year_over_year_growth",),
        period_start=date(2024, 12, 28),
        period_end=date(2026, 3, 31),
        point_count=5,
        source_branch_ids=("apple_revenue", "cloudflare_revenue", "tesla_revenue"),
    )
    memory = SessionMemory(recent_artifacts=(artifact,))
    current = ResolvedQuery(
        query="побудуй такий графік за період 2023-2025",
        metrics=("revenue",),
    )
    merged = _merge_follow_up_if_needed(current, analysis, memory)
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.RAG_ONLY),
    )
    state = create_initial_agent_state(
        "побудуй такий графік за період 2023-2025",
        session_id="session-artifact-period-override",
    )
    state["analysis"] = analysis
    state["resolved_query"] = merged
    state["session_memory"] = memory

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert model.model_calls == []
    plan = update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    assert "deterministic_recent_artifact_period_plan" in plan.reason_codes
    financial_branches = [
        branch for branch in plan.branches if isinstance(branch, FinancialFactsBranch)
    ]
    assert [branch.request.company_ids for branch in financial_branches] == [
        (APPLE_ID,),
        (COMPANY_ID,),
        (NETFLIX_ID,),
    ]
    assert all(branch.request.period_start == date(2022, 1, 1) for branch in financial_branches)
    assert all(branch.request.period_end == date(2025, 12, 31) for branch in financial_branches)
    assert [
        branch.operation for branch in plan.branches if isinstance(branch, CalculationBranch)
    ] == [
        "year_over_year_growth",
        "year_over_year_growth",
        "year_over_year_growth",
    ]
    chart = plan.branches[-1]
    assert isinstance(chart, ChartBranch)
    assert chart.title == "Apple vs Cloudflare vs Tesla Revenue Growth"
    assert chart.depends_on == (
        "artifact_1_revenue_growth",
        "artifact_2_revenue_growth",
        "artifact_3_revenue_growth",
    )


def test_follow_up_replays_previous_growth_chart_for_new_company_without_model_plan() -> None:
    analysis = QuestionAnalysis(
        normalized_question="do the same for zoom",
        route=ResearchRoute.RAG_ONLY,
        required_capabilities=(AgentCapability.DOCUMENTS, AgentCapability.CHART),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "same_chart"),
    )
    previous_plan = _previous_revenue_growth_chart_plan(MICROSOFT_ID)
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.RAG_ONLY),
    )
    state = create_initial_agent_state(
        "do the same for Zoom",
        session_id="session-replay-new-company",
    )
    state["analysis"] = analysis
    state["resolved_query"] = ResolvedQuery(
        query="do the same for Zoom",
        company_ids=(ZOOM_ID,),
        metrics=("revenue",),
    )
    state["session_memory"] = SessionMemory(last_execution_plan=previous_plan)

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert model.model_calls == []
    plan = update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    assert "deterministic_follow_up_replay_plan" in plan.reason_codes
    financial_branches = [
        branch for branch in plan.branches if isinstance(branch, FinancialFactsBranch)
    ]
    assert [branch.request.company_ids for branch in financial_branches] == [(ZOOM_ID,)]
    assert [
        branch.operation for branch in plan.branches if isinstance(branch, CalculationBranch)
    ] == ["year_over_year_growth"]
    chart = plan.branches[-1]
    assert isinstance(chart, ChartBranch)
    assert chart.chart_type == "line"
    reconciled = update["analysis"]
    assert isinstance(reconciled, QuestionAnalysis)
    assert reconciled.route is ResearchRoute.CALCULATION
    assert AgentCapability.DOCUMENTS not in reconciled.required_capabilities


def test_follow_up_replay_chart_title_uses_new_series_label() -> None:
    facts = FinancialFactsBranch(
        branch_id="replay_1_revenue_facts",
        request=FinancialFactQuery(company_ids=(ZOOM_ID,), metrics=("revenue",)),
    )
    calculation = CalculationBranch(
        branch_id="replay_1_revenue_calc",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    stale_chart = ChartBranch(
        branch_id="replay_chart",
        chart_type="line",
        dataset_ref=calculation.branch_id,
        depends_on=(calculation.branch_id,),
        title="Microsoft revenue YoY growth - last 8 quarters",
    )
    state = create_initial_agent_state(
        "Зроби те саме для Zoom",
        session_id="session-replay-title",
    )
    state["execution_plan"] = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(facts, calculation, stale_chart),
        reason_codes=("deterministic_follow_up_replay_plan",),
    )
    state["calculations"] = (
        CalculationBranchResult(
            branch_id="replay_1_revenue_calc",
            result=CalculationResult(
                operation="year_over_year_growth",
                values=(
                    CalculationPoint(
                        label="Zoom Communications, Inc. revenue 2026-04-30",
                        value=Decimal("5.47"),
                        observed_at=date(2026, 4, 30),
                    ),
                ),
                inputs=(),
                formula="(current / prior_year - 1) * 100",
                unit="percent",
                sources=("https://sec.example/zoom",),
            ),
        ),
    )
    state["branch_outcomes"] = (
        BranchOutcome(
            branch_id=calculation.branch_id,
            kind=calculation.kind,
            status=BranchStatus.COMPLETED,
            attempts=1,
        ),
    )

    update = _generate_chart_spec(state)

    chart = update["chart_spec"]
    assert chart.title == "Zoom Communications, Inc. revenue YoY"


def test_parse_failure_uses_follow_up_replay_analysis_for_same_data_chart() -> None:
    previous_plan = _previous_revenue_growth_chart_plan(MICROSOFT_ID)
    previous_resolved = ResolvedQuery(
        query="plot microsoft revenue growth",
        company_ids=(MICROSOFT_ID,),
        metrics=("revenue",),
    )
    memory = SessionMemory(
        last_resolved_query=previous_resolved,
        recent_resolved_queries=(previous_resolved,),
        last_execution_plan=previous_plan,
    )
    model = ParseFailureModelProvider(
        analysis=QuestionAnalysis(
            normalized_question="unused",
            route=ResearchRoute.UNSUPPORTED,
        ),
        plan=ExecutionPlan(route=ResearchRoute.UNSUPPORTED),
    )
    state = create_initial_agent_state(
        "Побудуй bar chart на цих самих даних",
        session_id="session-parse-fallback-same-data",
    )
    state["session_memory"] = memory

    parse_update = _parse_question(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert "status" not in parse_update
    assert "errors" not in parse_update
    analysis = parse_update["analysis"]
    assert isinstance(analysis, QuestionAnalysis)
    assert analysis.is_follow_up is True
    assert analysis.chart_requested is True
    assert analysis.route is ResearchRoute.CALCULATION
    assert "chart_type_override" in analysis.reason_codes

    state.update(parse_update)
    merged = _merge_follow_up_if_needed(
        ResolvedQuery(
            query="Побудуй bar chart на цих самих даних",
            metrics=("revenue",),
        ),
        analysis,
        memory,
    )
    state["resolved_query"] = merged
    plan_update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert ModelPurpose.PLAN not in model.purposes
    plan = plan_update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    chart = plan.branches[-1]
    assert isinstance(chart, ChartBranch)
    assert chart.chart_type == "bar"


def test_follow_up_replays_previous_chart_with_chart_type_override() -> None:
    analysis = QuestionAnalysis(
        normalized_question="build a bar chart from the same data",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "same_data", "chart_type_override"),
    )
    previous_plan = _previous_revenue_growth_chart_plan(MICROSOFT_ID)
    previous_resolved = ResolvedQuery(
        query="plot microsoft revenue growth",
        company_ids=(MICROSOFT_ID,),
        metrics=("revenue",),
    )
    memory = SessionMemory(
        last_resolved_query=previous_resolved,
        recent_resolved_queries=(previous_resolved,),
        last_execution_plan=previous_plan,
    )
    merged = _merge_follow_up_if_needed(
        ResolvedQuery(query="build a bar chart from the same data", metrics=("revenue",)),
        analysis,
        memory,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.RAG_ONLY),
    )
    state = create_initial_agent_state(
        "build a bar chart from the same data",
        session_id="session-replay-chart-type",
    )
    state["analysis"] = analysis
    state["resolved_query"] = merged
    state["session_memory"] = memory

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert model.model_calls == []
    assert merged.company_ids == (MICROSOFT_ID,)
    plan = update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    chart = plan.branches[-1]
    assert isinstance(chart, ChartBranch)
    assert chart.chart_type == "bar"
    assert chart.depends_on == ("replay_1_revenue_calc",)


def test_follow_up_replays_add_company_bar_chart_without_dropping_previous_company() -> None:
    analysis = QuestionAnalysis(
        normalized_question="додай amazon і побудуй bar chart",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
        is_follow_up=True,
        reason_codes=("follow_up", "adds_company", "explicit_chart_request"),
    )
    previous_plan = _previous_revenue_growth_chart_plan(MICROSOFT_ID)
    previous_resolved = ResolvedQuery(
        query="побудуй графік росту revenue microsoft",
        company_ids=(MICROSOFT_ID,),
        metrics=("revenue",),
    )
    memory = SessionMemory(
        last_resolved_query=previous_resolved,
        recent_resolved_queries=(previous_resolved,),
        last_execution_plan=previous_plan,
    )
    merged = _merge_follow_up_if_needed(
        ResolvedQuery(
            query="додай amazon і побудуй bar chart",
            entities=(
                EntityResolution(
                    kind="company",
                    mention="amazon",
                    status="resolved",
                    canonical_value=str(AMAZON_ID),
                    candidates=(
                        EntityCandidate(
                            id=AMAZON_ID,
                            canonical_value=str(AMAZON_ID),
                            display_value="AMAZON COM INC",
                            match_kind="sec_company_extracted",
                        ),
                    ),
                ),
            ),
            company_ids=(AMAZON_ID,),
            metrics=("revenue",),
        ),
        analysis,
        memory,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.RAG_ONLY),
    )
    state = create_initial_agent_state(
        "додай amazon і побудуй bar chart",
        session_id="session-replay-add-company-bar-chart",
    )
    state["analysis"] = analysis
    state["resolved_query"] = merged
    state["session_memory"] = memory

    update = _plan_request(
        state,
        Runtime(context=ResearchAgentRuntime(model, PeerAnnualFinancialTools())),
    )

    assert model.model_calls == []
    assert merged.company_ids == (MICROSOFT_ID, AMAZON_ID)
    plan = update["execution_plan"]
    assert isinstance(plan, ExecutionPlan)
    assert "errors" not in update
    assert [
        branch.request.company_ids
        for branch in plan.branches
        if isinstance(branch, FinancialFactsBranch)
    ] == [(MICROSOFT_ID,), (AMAZON_ID,)]
    chart = plan.branches[-1]
    assert isinstance(chart, ChartBranch)
    assert chart.chart_type == "bar"
    assert chart.depends_on == ("replay_1_revenue_calc", "replay_2_revenue_calc")


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


def test_financial_chart_without_company_abstains_before_planning() -> None:
    class NoCompanyTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            return ResolvedQuery(query=query, metrics=("revenue",))

    analysis = QuestionAnalysis(
        normalized_question="Plot revenue growth against the federal funds rate",
        route=ResearchRoute.HYBRID,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.MACRO_SERIES,
            AgentCapability.CALCULATIONS,
            AgentCapability.CHART,
        ),
        chart_requested=True,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.HYBRID, branches=(_financial_branch(),)),
    )
    tools = NoCompanyTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Plot revenue growth against the federal funds rate.",
        session_id="session-missing-company",
    )

    assert result["status"] is AgentRunStatus.ABSTAINED
    assert any(error.code == "missing_company" for error in result["errors"])
    assert ModelPurpose.PLAN not in model.purposes
    assert tools.calls["financial"] == 0
    assert tools.calls["macro"] == 0


def test_unresolved_follow_up_company_abstain_has_user_facing_answer() -> None:
    class UnresolvedSamsungTools(FakeResearchTools):
        def resolve_entities(self, query: str) -> ResolvedQuery:
            self.calls["resolve"] += 1
            return ResolvedQuery(
                query=query,
                entities=(
                    EntityResolution(
                        kind="public_company",
                        mention="SAMSUNG",
                        status="unresolved",
                    ),
                ),
                metrics=("revenue",),
            )

    analysis = QuestionAnalysis(
        normalized_question="Compare Samsung revenue growth over the last eight quarters.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
        is_follow_up=True,
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(route=ResearchRoute.CALCULATION),
        company_extraction=CompanyMentionExtraction(
            companies=(CompanyMentionCandidate(mention="SAMSUNG"),),
            reason_codes=("explicit_company_target",),
        ),
    )
    tools = UnresolvedSamsungTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "а тепер те саме для SAMSUNG",
        session_id="session-missing-follow-up-company",
    )

    frame = cast(ResearchFrame, result["research_frame"])
    assert result["status"] is AgentRunStatus.ABSTAINED
    assert any(error.code == "missing_company" for error in result["errors"])
    assert result["final_answer"] is not None
    assert "SAMSUNG" in result["final_answer"]
    assert "SEC/EDGAR" in result["final_answer"]
    assert "попередній компанії" in result["final_answer"]
    assert "ticker" in result["final_answer"]
    assert frame.company_targets[0].mention == "SAMSUNG"
    assert frame.company_targets[0].source == "current_question"
    assert not frame.inherited_from_previous
    assert ModelPurpose.PLAN not in model.purposes
    assert tools.calls["prepare"] == 0
    assert tools.calls["financial"] == 0


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

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["answer_validation"].valid is True
    assert result["final_answer"] is not None
    assert "125 USD" in result["final_answer"]
    assert model.purposes.count(ModelPurpose.REPAIR) == 1
    assert any(error.code == "openai_timeout" for error in result["errors"])


def test_answer_timeout_falls_back_to_deterministic_cited_summary() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare revenue growth",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS, AgentCapability.CALCULATIONS),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            _financial_branch(),
            CalculationBranch(
                branch_id="growth",
                operation="percentage_change",
                input_refs=("financial",),
                depends_on=("financial",),
            ),
        ),
    )
    model = AnswerTimeoutModelProvider(analysis=analysis, plan=plan)

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "Compare Cloudflare revenue growth.",
        session_id="session-answer-timeout-fallback",
        policy=ExecutionPolicy(max_retries_per_node=1),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["final_answer"] is not None
    assert "[calculation:growth]" in result["final_answer"]
    assert "\n\n| Period | Company | Metric | Value |" in result["final_answer"]
    assert result["answer_validation"].valid is True
    assert any(error.code == "openai_timeout" for error in result["errors"])


def test_answer_timeout_fallback_formats_multi_point_calculations() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare revenue growth",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS, AgentCapability.CALCULATIONS),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            _financial_branch(),
            CalculationBranch(
                branch_id="growth",
                operation="year_over_year_growth",
                input_refs=("financial",),
                depends_on=("financial",),
            ),
        ),
    )
    model = AnswerTimeoutModelProvider(analysis=analysis, plan=plan)

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, AnnualSeriesFinancialTools())).run(
        "Compare Cloudflare revenue growth.",
        session_id="session-answer-timeout-series-fallback",
        policy=ExecutionPolicy(max_retries_per_node=0),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["final_answer"] is not None
    assert "latest value was 25% at 2025-12-31" in result["final_answer"]
    assert "[calculation:growth]" in result["final_answer"]
    assert "[{'label':" not in result["final_answer"]
    assert "'observed_at':" not in result["final_answer"]
    assert result["answer_validation"].valid is True


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


def test_answer_generation_uses_human_number_display_values() -> None:
    latest_fact_id = uuid.UUID("99999999-9999-9999-9999-999999999999")

    class LargeNumberFinancialTools(FakeResearchTools):
        def query_financial_facts(self, request: FinancialFactQuery) -> FinancialFactQueryResult:
            self.calls["financial"] += 1
            previous = _financial_observation(
                date(2025, 12, 31), Decimal("81273000000.000000")
            ).model_copy(
                update={
                    "id": uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
                    "company_id": COMPANY_ID,
                    "company_name": "MICROSOFT CORP",
                    "ticker": "MSFT",
                    "period_type": "quarter",
                    "fiscal_period": "Q4",
                }
            )
            latest = _financial_observation(
                date(2026, 3, 31), Decimal("82886000000.000000")
            ).model_copy(
                update={
                    "id": latest_fact_id,
                    "company_id": COMPANY_ID,
                    "company_name": "MICROSOFT CORP",
                    "ticker": "MSFT",
                    "period_type": "quarter",
                    "fiscal_period": "Q1",
                }
            )
            return FinancialFactQueryResult(
                query=request,
                observations=(previous, latest),
                available_units=("USD",),
            )

    analysis = QuestionAnalysis(
        normalized_question="Compare Microsoft revenue growth.",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(
            AgentCapability.FINANCIAL_FACTS,
            AgentCapability.CALCULATIONS,
        ),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.CALCULATION,
        branches=(
            FinancialFactsBranch(
                branch_id="financial",
                request=FinancialFactQuery(
                    company_ids=(COMPANY_ID,),
                    metrics=("revenue",),
                ),
            ),
            CalculationBranch(
                branch_id="growth",
                operation="percentage_change",
                input_refs=("financial",),
                depends_on=("financial",),
            ),
        ),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        texts=(
            "MICROSOFT CORP revenue was 82886000000.000000 USD "
            f"[financial_fact:{latest_fact_id}]. Revenue growth was "
            "1.984668955249590885041772800% [calculation:growth].",
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, LargeNumberFinancialTools())).run(
        "Compare Microsoft revenue growth.",
        session_id="session-human-number-formatting",
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["final_answer"] is not None
    assert "82886000000.000000" not in result["final_answer"]
    assert "1.984668955249590885041772800" not in result["final_answer"]
    assert "82.89 billion USD" in result["final_answer"]
    assert "1.98%" in result["final_answer"]
    answer_context = next(
        messages[-1].content
        for purpose, messages in model.model_calls
        if purpose is ModelPurpose.ANSWER
    )
    assert "82886000000.000000" not in answer_context
    assert "1.984668955249590885041772800" not in answer_context
    assert "82.89 billion USD" in answer_context
    assert "1.98%" in answer_context
    assert all("82886000000.000000" not in item.label for item in result["citations"])


def test_answer_timeout_fallback_groups_peer_facts_by_period() -> None:
    analysis = QuestionAnalysis(
        normalized_question="Compare Cloudflare and Netflix revenue growth",
        route=ResearchRoute.CALCULATION,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS, AgentCapability.CALCULATIONS),
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
    model = AnswerTimeoutModelProvider(
        analysis=analysis,
        plan=ExecutionPlan(
            route=ResearchRoute.CALCULATION,
            branches=(cloudflare_facts, netflix_facts, cloudflare_growth, netflix_growth),
        ),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, PeerAnnualFinancialTools())).run(
        "Compare Cloudflare and Netflix revenue growth.",
        session_id="session-peer-fallback-table",
        policy=ExecutionPolicy(max_retries_per_node=0),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["final_answer"] is not None
    assert "| Period | Metric | Cloudflare | Netflix |" in result["final_answer"]
    assert "| 2025-12-31 | revenue | 125 USD " in result["final_answer"]
    assert " | 165 USD " in result["final_answer"]
    assert "| 2025-12-31 | Cloudflare | revenue |" not in result["final_answer"]
    assert result["answer_validation"].valid is True


def test_validation_failure_falls_back_to_deterministic_cited_summary() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What was revenue?",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.STRUCTURED_ONLY,
        branches=(_financial_branch(),),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        texts=(f"Cloudflare revenue was 124.6 USD [financial_fact:{FACT_ID}].",),
    )

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, FakeResearchTools())).run(
        "What was Cloudflare revenue?",
        session_id="session-validation-fallback",
        policy=ExecutionPolicy(max_repair_attempts=0),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["answer_validation"].valid is True
    assert "\n\n| Period | Company | Metric | Value |" in result["final_answer"]
    assert "125 USD" in result["final_answer"]
    assert "124.6" not in result["final_answer"]
    assert "[financial_fact:" in result["final_answer"]


def test_validation_fallback_avoids_sentence_split_in_punctuated_company_name() -> None:
    analysis = QuestionAnalysis(
        normalized_question="What was revenue?",
        route=ResearchRoute.STRUCTURED_ONLY,
        required_capabilities=(AgentCapability.FINANCIAL_FACTS,),
    )
    plan = ExecutionPlan(
        route=ResearchRoute.STRUCTURED_ONLY,
        branches=(_financial_branch(),),
    )
    model = FakeModelProvider(
        analysis=analysis,
        plan=plan,
        texts=(f"Elastic N.V. revenue was 124.6 USD [financial_fact:{FACT_ID}].",),
    )

    result = ResearchAgent(
        runtime=ResearchAgentRuntime(model, PunctuatedCompanyFinancialTools())
    ).run(
        "What was Elastic revenue?",
        session_id="session-punctuated-company-validation-fallback",
        policy=ExecutionPolicy(max_repair_attempts=0),
    )

    assert result["status"] is AgentRunStatus.COMPLETED
    assert result["answer_validation"].valid is True
    assert "| 2025-12-31 | Elastic NV | revenue | 125 USD" in result["final_answer"]


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


def test_parse_failure_abstains_with_explanation_and_rewrites() -> None:
    model = ParseFailureModelProvider(
        analysis=QuestionAnalysis(
            normalized_question="unused",
            route=ResearchRoute.UNSUPPORTED,
        ),
        plan=ExecutionPlan(route=ResearchRoute.UNSUPPORTED),
    )
    tools = FakeResearchTools()

    result = ResearchAgent(runtime=ResearchAgentRuntime(model, tools)).run(
        "Plot Cloudflare revenue growth against the Netflix",
        session_id="session-parse-failure",
    )

    assert result["status"] is AgentRunStatus.ABSTAINED
    assert result["final_answer"] is not None
    assert "could not classify the request" in result["final_answer"]
    assert "Unexpected OpenAI provider failure." not in result["final_answer"]
    assert (
        "Plot Cloudflare revenue growth against Netflix revenue growth." in result["final_answer"]
    )
    assert any(error.code == "openai_unexpected" for error in result["errors"])
    assert ModelPurpose.PLAN not in model.purposes
    assert tools.calls == {}
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


def _previous_revenue_growth_chart_plan(company_id: uuid.UUID) -> ExecutionPlan:
    facts = FinancialFactsBranch(
        branch_id="previous_revenue",
        request=FinancialFactQuery(
            company_ids=(company_id,),
            metrics=("revenue",),
            period_types=("quarter",),
            limit=8,
        ),
    )
    growth = CalculationBranch(
        branch_id="previous_growth",
        operation="year_over_year_growth",
        input_refs=(facts.branch_id,),
        depends_on=(facts.branch_id,),
    )
    chart = ChartBranch(
        branch_id="previous_chart",
        chart_type="line",
        dataset_ref=growth.branch_id,
        depends_on=(growth.branch_id,),
        title="Revenue growth",
    )
    return ExecutionPlan(route=ResearchRoute.CALCULATION, branches=(facts, growth, chart))


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
