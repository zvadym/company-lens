from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from company_lens.agent.output import ResearchCitationOutput, ResearchExecutionOutput
from company_lens.agent.schemas import (
    AgentCapability,
    AgentError,
    AgentRunStatus,
    CalculationOperation,
    ExecutionPolicy,
    ResearchRoute,
)
from company_lens.analytics.schemas import ChartSpecification
from company_lens.evidence.schemas import SourcePreview
from company_lens.retrieval.adaptive_schemas import RetrievalStrategy


class ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)


class ResearchRunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLATION_REQUESTED = "cancellation_requested"
    COMPLETED = "completed"
    PARTIAL = "partial"
    ABSTAINED = "abstained"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def terminal(self) -> bool:
        return self in {
            self.COMPLETED,
            self.PARTIAL,
            self.ABSTAINED,
            self.FAILED,
            self.CANCELLED,
            self.TIMED_OUT,
        }


class StartResearchRequest(ApiModel):
    question: str = Field(min_length=1, max_length=4_000)
    session_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("question cannot be blank")
        return cleaned


class ResearchAccepted(ApiModel):
    run_id: uuid.UUID
    session_id: str
    status: Literal[ResearchRunStatus.QUEUED] = ResearchRunStatus.QUEUED
    run_url: str
    events_url: str
    sources_url: str


class ResearchResult(ApiModel):
    agent_status: AgentRunStatus
    answer: str | None = None
    citations: tuple[ResearchCitationOutput, ...] = ()
    chart: ChartSpecification | None = None
    warnings: tuple[AgentError, ...] = ()
    execution: ResearchExecutionOutput
    sources: tuple[SourcePreview, ...] = ()


class ResearchRunResponse(ApiModel):
    run_id: uuid.UUID
    session_id: str
    status: ResearchRunStatus
    question: str
    result: ResearchResult | None = None
    error_code: str | None = None
    error_message: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    deadline_at: datetime
    cancellation_requested_at: datetime | None = None


class ResearchRunListResponse(ApiModel):
    items: tuple[ResearchRunResponse, ...]
    total: int = Field(ge=0)


class ResearchSourcesResponse(ApiModel):
    run_id: uuid.UUID
    sources: tuple[SourcePreview, ...] = ()


class FeedbackRequest(ApiModel):
    run_id: uuid.UUID
    rating: Literal["positive", "negative"]
    comment: str | None = Field(default=None, max_length=2_000)
    actor_id: str | None = Field(default=None, min_length=1, max_length=128)


class FeedbackResponse(ApiModel):
    feedback_id: uuid.UUID
    run_id: uuid.UUID
    rating: Literal["positive", "negative"]
    created_at: datetime


class CompanyOutput(ApiModel):
    id: uuid.UUID
    display_name: str
    legal_name: str
    cik: str | None = None
    primary_ticker: str | None = None
    exchange: str | None = None


class CompaniesResponse(ApiModel):
    items: tuple[CompanyOutput, ...]
    total: int


ResearchEventType = Literal[
    "run.status",
    "analysis.summary",
    "entities.summary",
    "plan.summary",
    "node.status",
    "tool.call",
    "tool.status",
    "retrieval.summary",
    "validation.summary",
    "chart.ready",
    "answer.token",
    "run.terminal",
]


class RunStatusEventData(ApiModel):
    status: ResearchRunStatus


class AnalysisSummaryEventData(ApiModel):
    route: ResearchRoute
    required_capabilities: tuple[AgentCapability, ...] = ()
    chart_requested: bool = False
    is_follow_up: bool = False
    reason_codes: tuple[str, ...] = ()


class EntityCandidateOutput(ApiModel):
    canonical_value: str
    display_value: str
    match_kind: str


class EntityResolutionOutput(ApiModel):
    kind: str
    mention: str
    status: Literal["resolved", "ambiguous", "unresolved"]
    canonical_value: str | None = None
    candidates: tuple[EntityCandidateOutput, ...] = ()


class EntitiesSummaryEventData(ApiModel):
    entities: tuple[EntityResolutionOutput, ...] = ()
    company_ids: tuple[uuid.UUID, ...] = ()
    accession_numbers: tuple[str, ...] = ()
    filing_forms: tuple[str, ...] = ()
    fiscal_years: tuple[int, ...] = ()
    fiscal_periods: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    has_ambiguity: bool = False


class RetrievalBranchSummary(ApiModel):
    kind: Literal["retrieve_documents"] = "retrieve_documents"
    branch_id: str
    depends_on: tuple[str, ...] = ()
    optional: bool = False
    query: str
    max_attempts: int
    index_name: str
    index_version: str


class FinancialBranchSummary(ApiModel):
    kind: Literal["query_financial_facts"] = "query_financial_facts"
    branch_id: str
    depends_on: tuple[str, ...] = ()
    optional: bool = False
    company_ids: tuple[uuid.UUID, ...] = ()
    tickers: tuple[str, ...] = ()
    metrics: tuple[str, ...]
    period_start: str | None = None
    period_end: str | None = None
    fiscal_years: tuple[int, ...] = ()
    fiscal_periods: tuple[str, ...] = ()
    units: tuple[str, ...] = ()
    limit: int


class MacroBranchSummary(ApiModel):
    kind: Literal["query_macro_series"] = "query_macro_series"
    branch_id: str
    depends_on: tuple[str, ...] = ()
    optional: bool = False
    series_ids: tuple[str, ...]
    observation_start: str | None = None
    observation_end: str | None = None
    include_missing: bool = False
    limit: int


class CalculationBranchSummary(ApiModel):
    kind: Literal["calculate_metrics"] = "calculate_metrics"
    branch_id: str
    depends_on: tuple[str, ...] = ()
    optional: bool = False
    operation: CalculationOperation
    input_refs: tuple[str, ...]
    years: str | None = None
    window: int | None = None
    base: str


class ChartBranchSummary(ApiModel):
    kind: Literal["generate_chart_spec"] = "generate_chart_spec"
    branch_id: str
    depends_on: tuple[str, ...] = ()
    optional: bool = False
    chart_type: Literal["line", "bar", "area", "scatter"]
    dataset_ref: str
    title: str
    x_label: str


ExecutionBranchSummary = Annotated[
    RetrievalBranchSummary
    | FinancialBranchSummary
    | MacroBranchSummary
    | CalculationBranchSummary
    | ChartBranchSummary,
    Field(discriminator="kind"),
]


class PlanSummaryEventData(ApiModel):
    route: ResearchRoute
    requires_citations: bool
    reason_codes: tuple[str, ...] = ()
    branches: tuple[ExecutionBranchSummary, ...] = ()


class NodeStatusEventData(ApiModel):
    step_id: str
    node: str
    branch_id: str | None = None
    status: Literal["started", "completed", "failed", "skipped"]
    attempt: int = Field(ge=1)
    summary: str
    duration_ms: int | None = Field(default=None, ge=0)


class RetrievalAttemptOutput(ApiModel):
    attempt: int = Field(ge=1)
    strategy: RetrievalStrategy
    action: str
    reason: str | None = None
    evidence_count: int = Field(ge=0)
    context_tokens: int = Field(ge=0)


class RetrievalToolResultSummary(ApiModel):
    kind: Literal["retrieve_documents"] = "retrieve_documents"
    strategy: RetrievalStrategy
    evidence_count: int = Field(ge=0)
    context_tokens: int = Field(ge=0)
    attempts: tuple[RetrievalAttemptOutput, ...] = ()
    abstained: bool = False
    abstention_reason: str | None = None


class FinancialToolResultSummary(ApiModel):
    kind: Literal["query_financial_facts"] = "query_financial_facts"
    observation_count: int = Field(ge=0)
    metrics: tuple[str, ...] = ()
    available_units: tuple[str, ...] = ()
    warning_count: int = Field(ge=0)
    warnings: tuple[str, ...] = ()


class MacroToolResultSummary(ApiModel):
    kind: Literal["query_macro_series"] = "query_macro_series"
    series_count: int = Field(ge=0)
    observation_count: int = Field(ge=0)
    series_ids: tuple[str, ...] = ()
    warning_count: int = Field(ge=0)
    warnings: tuple[str, ...] = ()


class CalculationToolResultSummary(ApiModel):
    kind: Literal["calculate_metrics"] = "calculate_metrics"
    operation: CalculationOperation
    formula: str
    unit: str
    output_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    warnings: tuple[str, ...] = ()


ToolResultSummary = Annotated[
    RetrievalToolResultSummary
    | FinancialToolResultSummary
    | MacroToolResultSummary
    | CalculationToolResultSummary,
    Field(discriminator="kind"),
]


class ToolStatusEventData(ApiModel):
    branch_id: str
    kind: Literal[
        "retrieve_documents",
        "query_financial_facts",
        "query_macro_series",
        "calculate_metrics",
    ]
    status: Literal["started", "completed", "failed", "skipped"]
    attempts: int = Field(ge=0)
    optional: bool = False
    cache_hit: bool = False
    duration_ms: int | None = Field(default=None, ge=0)
    result: ToolResultSummary | None = None
    error_code: str | None = None


class ValidationSummaryEventData(ApiModel):
    valid: bool
    claim_count: int = Field(ge=0)
    material_claim_count: int = Field(ge=0)
    supported_claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    cited_evidence_count: int = Field(ge=0)
    issue_count: int = Field(ge=0)
    reason_codes: tuple[str, ...] = ()
    repair_attempt: int = Field(ge=0)
    semantic_supported_count: int = Field(ge=0)
    semantic_unsupported_count: int = Field(ge=0)
    semantic_unavailable_count: int = Field(ge=0)


class ChartReadyEventData(ApiModel):
    chart_type: Literal["line", "bar", "area", "scatter"]
    title: str
    series_count: int = Field(ge=0)
    point_count: int = Field(ge=0)
    source_count: int = Field(ge=0)


class AnswerTokenEventData(ApiModel):
    index: int = Field(ge=0)
    delta: str


class RunTerminalEventData(ApiModel):
    status: ResearchRunStatus
    error_code: str | None = None


ResearchEventDataV2 = (
    RunStatusEventData
    | AnalysisSummaryEventData
    | EntitiesSummaryEventData
    | PlanSummaryEventData
    | NodeStatusEventData
    | ToolStatusEventData
    | ValidationSummaryEventData
    | ChartReadyEventData
    | AnswerTokenEventData
    | RunTerminalEventData
)

EVENT_DATA_V2_MODELS: dict[str, type[ApiModel]] = {
    "run.status": RunStatusEventData,
    "analysis.summary": AnalysisSummaryEventData,
    "entities.summary": EntitiesSummaryEventData,
    "plan.summary": PlanSummaryEventData,
    "node.status": NodeStatusEventData,
    "tool.status": ToolStatusEventData,
    "validation.summary": ValidationSummaryEventData,
    "chart.ready": ChartReadyEventData,
    "answer.token": AnswerTokenEventData,
    "run.terminal": RunTerminalEventData,
}


class ResearchEventEnvelope(ApiModel):
    id: int
    schema_version: Literal["1", "2"]
    run_id: uuid.UUID
    type: ResearchEventType
    occurred_at: datetime
    data: dict[str, object] | ResearchEventDataV2

    @model_validator(mode="before")
    @classmethod
    def validate_typed_event_data(cls, value: object) -> object:
        if not isinstance(value, dict) or value.get("schema_version") != "2":
            return value
        event_type = value.get("type")
        model = EVENT_DATA_V2_MODELS.get(str(event_type))
        if model is None:
            raise ValueError(f"Unsupported version 2 event type: {event_type}")
        updated = dict(value)
        updated["data"] = model.model_validate(value.get("data"))
        return updated


class PublicErrorDetail(ApiModel):
    code: str
    message: str
    correlation_id: str | None = None


class PublicErrorResponse(ApiModel):
    error: PublicErrorDetail
