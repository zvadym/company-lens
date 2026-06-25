from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal, NotRequired, Required, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from company_lens.analytics.schemas import CalculationResult, ChartSpecification
from company_lens.evidence.schemas import (
    AnswerValidation as AnswerValidation,
)
from company_lens.evidence.schemas import (
    CitationReference as CitationReference,
)
from company_lens.evidence.schemas import (
    ClaimRecord as ClaimRecord,
)
from company_lens.evidence.schemas import (
    EvidenceEnvelope as EvidenceEnvelope,
)
from company_lens.evidence.schemas import (
    EvidenceKind as EvidenceKind,
)
from company_lens.evidence.schemas import (
    SourcePreview,
)
from company_lens.financials.schemas import FinancialFactQuery, FinancialFactQueryResult
from company_lens.macro.schemas import FredSeriesQuery, FredSeriesResult
from company_lens.retrieval.adaptive_schemas import (
    AdaptiveRetrievalRequest,
    AdaptiveRetrievalResponse,
    ResolvedQuery,
)


class ResearchRoute(enum.StrEnum):
    RAG_ONLY = "rag_only"
    STRUCTURED_ONLY = "structured_only"
    API_ONLY = "api_only"
    CALCULATION = "calculation"
    HYBRID = "hybrid"
    UNSUPPORTED = "unsupported"


class AgentCapability(enum.StrEnum):
    DOCUMENTS = "documents"
    FINANCIAL_FACTS = "financial_facts"
    MACRO_SERIES = "macro_series"
    CALCULATIONS = "calculations"
    CHART = "chart"


class AgentRunStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    ABSTAINED = "abstained"
    FAILED = "failed"


class AgentErrorSeverity(enum.StrEnum):
    RECOVERABLE = "recoverable"
    TERMINAL = "terminal"


class AgentErrorCategory(enum.StrEnum):
    VALIDATION = "validation"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_CONNECTION = "provider_connection"
    PROVIDER_AUTH = "provider_auth"
    PROVIDER_SERVICE = "provider_service"
    PROVIDER_REFUSAL = "provider_refusal"
    PROVIDER_RESPONSE = "provider_response"
    TOOL = "tool"
    BUDGET = "budget"
    INTERNAL = "internal"


class TrajectoryStatus(enum.StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class BranchStatus(enum.StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class QuestionAnalysis(FrozenModel):
    normalized_question: str = Field(min_length=1)
    route: ResearchRoute
    required_capabilities: tuple[AgentCapability, ...] = ()
    chart_requested: bool = False
    is_follow_up: bool = False
    reason_codes: tuple[str, ...] = ()

    @field_validator("normalized_question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("normalized_question cannot be blank.")
        return cleaned

    @model_validator(mode="after")
    def validate_analysis(self) -> QuestionAnalysis:
        if len(self.required_capabilities) != len(set(self.required_capabilities)):
            raise ValueError("required_capabilities must be unique.")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("reason_codes must be unique.")
        if any(not _is_reason_code(value) for value in self.reason_codes):
            raise ValueError("reason_codes must use lowercase snake_case identifiers.")
        if self.route is ResearchRoute.UNSUPPORTED and self.required_capabilities:
            raise ValueError("unsupported questions cannot request capabilities.")
        if self.chart_requested and AgentCapability.CHART not in self.required_capabilities:
            raise ValueError("chart_requested requires the chart capability.")
        return self


class CompanyMentionExtraction(FrozenModel):
    mentions: tuple[str, ...] = ()
    new_company_target: bool = False
    reason_codes: tuple[str, ...] = ()

    @field_validator("mentions")
    @classmethod
    def normalize_mentions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(dict.fromkeys(" ".join(item.split()) for item in value if item.strip()))
        if any(len(item) > 120 for item in cleaned):
            raise ValueError("mentions must be concise company names or tickers.")
        return cleaned

    @model_validator(mode="after")
    def validate_extraction(self) -> CompanyMentionExtraction:
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("reason_codes must be unique.")
        if any(not _is_reason_code(value) for value in self.reason_codes):
            raise ValueError("reason_codes must use lowercase snake_case identifiers.")
        return self


class ExecutionPolicy(FrozenModel):
    max_tool_calls: int = Field(default=10, ge=1, le=100)
    max_retries_per_node: int = Field(default=2, ge=0, le=10)
    max_repair_attempts: int = Field(default=1, ge=0, le=5)


class BranchBase(FrozenModel):
    branch_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    depends_on: tuple[str, ...] = ()
    optional: bool = False


class DocumentRetrievalBranch(BranchBase):
    kind: Literal["retrieve_documents"] = "retrieve_documents"
    request: AdaptiveRetrievalRequest


class FinancialFactsBranch(BranchBase):
    kind: Literal["query_financial_facts"] = "query_financial_facts"
    request: FinancialFactQuery


class MacroSeriesBranch(BranchBase):
    kind: Literal["query_macro_series"] = "query_macro_series"
    request: FredSeriesQuery


CalculationOperation = Literal[
    "quarter_over_quarter_growth",
    "year_over_year_growth",
    "cagr",
    "margin",
    "absolute_change",
    "percentage_change",
    "rolling_average",
    "normalised_index",
    "correlation",
]


class CalculationBranch(BranchBase):
    kind: Literal["calculate_metrics"] = "calculate_metrics"
    operation: CalculationOperation
    input_refs: tuple[str, ...] = Field(min_length=1)
    years: Decimal | None = Field(default=None, gt=0)
    window: int | None = Field(default=None, ge=1)
    base: Decimal = Field(default=Decimal("100"))

    @model_validator(mode="after")
    def validate_operation_inputs(self) -> CalculationBranch:
        single_input = {
            "quarter_over_quarter_growth",
            "year_over_year_growth",
            "cagr",
            "absolute_change",
            "percentage_change",
            "rolling_average",
            "normalised_index",
        }
        expected = 1 if self.operation in single_input else 2
        if len(self.input_refs) != expected:
            raise ValueError(f"{self.operation} requires exactly {expected} input reference(s).")
        if self.operation == "cagr" and self.years is None:
            raise ValueError("cagr requires years.")
        if self.operation == "rolling_average" and self.window is None:
            raise ValueError("rolling_average requires window.")
        return self


class ChartBranch(BranchBase):
    kind: Literal["generate_chart_spec"] = "generate_chart_spec"
    chart_type: Literal["line", "bar", "area", "scatter"]
    dataset_ref: str = Field(min_length=1)
    title: str = Field(min_length=1)
    x_label: str = Field(default="Date", min_length=1)


ExecutionBranch = Annotated[
    DocumentRetrievalBranch
    | FinancialFactsBranch
    | MacroSeriesBranch
    | CalculationBranch
    | ChartBranch,
    Field(discriminator="kind"),
]


class ModelExecutionBranch(FrozenModel):
    """OpenAI-compatible planning DTO without a JSON Schema ``oneOf`` union."""

    kind: Literal[
        "retrieve_documents",
        "query_financial_facts",
        "query_macro_series",
        "calculate_metrics",
        "generate_chart_spec",
    ]
    branch_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    depends_on: tuple[str, ...] = ()
    optional: bool = False
    retrieval_request: AdaptiveRetrievalRequest | None = None
    financial_request: FinancialFactQuery | None = None
    macro_request: FredSeriesQuery | None = None
    operation: CalculationOperation | None = None
    input_refs: tuple[str, ...] = ()
    years: float | None = Field(default=None, gt=0)
    window: int | None = Field(default=None, ge=1)
    base: float = 100.0
    chart_type: Literal["line", "bar", "area", "scatter"] | None = None
    dataset_ref: str | None = None
    title: str | None = None
    x_label: str = "Date"


class ModelExecutionPlan(FrozenModel):
    """Structured-output DTO converted into the stricter domain ``ExecutionPlan``."""

    route: ResearchRoute
    branches: tuple[ModelExecutionBranch, ...] = ()
    requires_citations: bool = True
    reason_codes: tuple[str, ...] = ()


class ExecutionPlan(FrozenModel):
    route: ResearchRoute
    branches: tuple[ExecutionBranch, ...] = ()
    requires_citations: bool = True
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_plan(self) -> ExecutionPlan:
        identifiers = [branch.branch_id for branch in self.branches]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Execution branch IDs must be unique.")
        known = set(identifiers)
        for branch in self.branches:
            if branch.branch_id in branch.depends_on:
                raise ValueError("Execution branches cannot depend on themselves.")
            unknown = set(branch.depends_on) - known
            if unknown:
                raise ValueError(f"Unknown branch dependencies: {sorted(unknown)}")
        _validate_acyclic_dependencies(self.branches)
        if self.route is ResearchRoute.UNSUPPORTED and self.branches:
            raise ValueError("Unsupported execution plans cannot contain branches.")
        if any(not _is_reason_code(value) for value in self.reason_codes):
            raise ValueError("reason_codes must use lowercase snake_case identifiers.")
        if len(self.reason_codes) != len(set(self.reason_codes)):
            raise ValueError("reason_codes must be unique.")
        return self


CompanyTargetStatus = Literal["resolved", "unresolved", "ambiguous"]
CompanyTargetSource = Literal["current_question", "follow_up_context", "prepared_ticker"]
FinancialDataReadinessStatus = Literal["available", "partial", "missing"]


class CompanyTarget(FrozenModel):
    mention: str = Field(min_length=1)
    company_id: uuid.UUID | None = None
    ticker: str | None = None
    display_name: str | None = None
    status: CompanyTargetStatus
    source: CompanyTargetSource


class FinancialDataReadiness(FrozenModel):
    company_id: uuid.UUID
    metric: str = Field(min_length=1)
    status: FinancialDataReadinessStatus
    observation_count: int = Field(default=0, ge=0)
    warnings: tuple[str, ...] = ()


class ResearchFrame(FrozenModel):
    question: str = Field(min_length=1)
    analysis: QuestionAnalysis
    resolved_query: ResolvedQuery
    company_targets: tuple[CompanyTarget, ...] = ()
    inherited_from_previous: bool = False
    follow_up_operation: CalculationOperation | None = None
    follow_up_window: int | None = Field(default=None, ge=1)
    financial_readiness: tuple[FinancialDataReadiness, ...] = ()


class SessionMessage(FrozenModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1)
    created_at: datetime

    @field_validator("content")
    @classmethod
    def content_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Session message content cannot be blank.")
        return value


class AgentError(FrozenModel):
    category: AgentErrorCategory
    severity: AgentErrorSeverity
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1)
    node: str | None = None
    attempt: int = Field(default=1, ge=1)

    @property
    def recoverable(self) -> bool:
        return self.severity is AgentErrorSeverity.RECOVERABLE


class TrajectoryEvent(FrozenModel):
    node: str = Field(min_length=1)
    status: TrajectoryStatus
    occurred_at: datetime
    summary: str = Field(min_length=1)
    duration_ms: int | None = Field(default=None, ge=0)
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class NodeAttempt(FrozenModel):
    node: str = Field(min_length=1)
    attempts: int = Field(ge=1)


class BranchOutcome(FrozenModel):
    branch_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    kind: str = Field(min_length=1)
    status: BranchStatus
    optional: bool = False
    attempts: int = Field(ge=0)
    error: AgentError | None = None

    @model_validator(mode="after")
    def validate_error(self) -> BranchOutcome:
        if (self.status is BranchStatus.FAILED) != (self.error is not None):
            raise ValueError("Failed branch outcomes require exactly one error.")
        return self


class RetrievalBranchResult(FrozenModel):
    branch_id: str
    result: AdaptiveRetrievalResponse


class FinancialBranchResult(FrozenModel):
    branch_id: str
    result: FinancialFactQueryResult


class MacroBranchResult(FrozenModel):
    branch_id: str
    result: FredSeriesResult


class CalculationBranchResult(FrozenModel):
    branch_id: str
    result: CalculationResult


class CachedSourceResult(FrozenModel):
    kind: Literal["retrieve_documents", "query_financial_facts", "query_macro_series"]
    request_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    stored_at: datetime
    retrieval_result: AdaptiveRetrievalResponse | None = None
    financial_result: FinancialFactQueryResult | None = None
    macro_result: FredSeriesResult | None = None

    @model_validator(mode="after")
    def validate_typed_result(self) -> CachedSourceResult:
        populated = sum(
            result is not None
            for result in (self.retrieval_result, self.financial_result, self.macro_result)
        )
        expected = {
            "retrieve_documents": self.retrieval_result,
            "query_financial_facts": self.financial_result,
            "query_macro_series": self.macro_result,
        }[self.kind]
        if populated != 1 or expected is None:
            raise ValueError("Cached source result must match its branch kind.")
        return self


class SessionArtifactContext(FrozenModel):
    artifact_id: str
    run_id: uuid.UUID
    kind: Literal["chart"] = "chart"
    user_question: str
    title: str | None = None
    chart_type: str | None = None
    series_labels: tuple[str, ...] = ()
    company_ids: tuple[uuid.UUID, ...] = ()
    metrics: tuple[str, ...] = ()
    calculations: tuple[str, ...] = ()
    period_start: date | None = None
    period_end: date | None = None
    point_count: int | None = None
    source_branch_ids: tuple[str, ...] = ()


class SessionMemory(FrozenModel):
    last_resolved_query: ResolvedQuery | None = None
    recent_resolved_queries: tuple[ResolvedQuery, ...] = ()
    last_execution_plan: ExecutionPlan | None = None
    last_chart_spec: ChartSpecification | None = None
    recent_artifacts: tuple[SessionArtifactContext, ...] = ()
    cached_source_results: tuple[CachedSourceResult, ...] = ()
    evidence: tuple[EvidenceEnvelope, ...] = ()
    updated_at: datetime | None = None


def append_tuple[ItemT](
    left: tuple[ItemT, ...] | list[ItemT],
    right: tuple[ItemT, ...] | list[ItemT],
) -> tuple[ItemT, ...]:
    """Append checkpointed collection values while restoring tuple immutability."""

    return (*tuple(left), *tuple(right))


def add_int(left: int, right: int) -> int:
    return left + right


class AgentState(TypedDict, total=False):
    run_id: Required[uuid.UUID]
    session_id: Required[str]
    question: Required[str]
    policy: Required[ExecutionPolicy]
    status: Required[AgentRunStatus]
    messages: Annotated[tuple[SessionMessage, ...], append_tuple]
    session_memory: NotRequired[SessionMemory]
    analysis: NotRequired[QuestionAnalysis | None]
    resolved_query: NotRequired[ResolvedQuery | None]
    research_frame: NotRequired[ResearchFrame | None]
    execution_plan: NotRequired[ExecutionPlan | None]
    active_branch: NotRequired[ExecutionBranch]
    retrieval_results: Annotated[tuple[RetrievalBranchResult, ...], append_tuple]
    financial_results: Annotated[tuple[FinancialBranchResult, ...], append_tuple]
    macro_results: Annotated[tuple[MacroBranchResult, ...], append_tuple]
    calculations: Annotated[tuple[CalculationBranchResult, ...], append_tuple]
    branch_outcomes: Annotated[tuple[BranchOutcome, ...], append_tuple]
    evidence: NotRequired[tuple[EvidenceEnvelope, ...]]
    chart_spec: NotRequired[ChartSpecification | None]
    draft_answer: NotRequired[str | None]
    final_answer: NotRequired[str | None]
    answer_validation: NotRequired[AnswerValidation]
    claims: NotRequired[tuple[ClaimRecord, ...]]
    repair_attempts: NotRequired[int]
    citations: NotRequired[tuple[CitationReference, ...]]
    source_previews: NotRequired[tuple[SourcePreview, ...]]
    errors: Annotated[tuple[AgentError, ...], append_tuple]
    trajectory: Annotated[tuple[TrajectoryEvent, ...], append_tuple]
    node_attempts: Annotated[tuple[NodeAttempt, ...], append_tuple]
    tool_calls_used: Annotated[int, add_int]


def _is_reason_code(value: str) -> bool:
    if not value or not value[0].islower():
        return False
    return all(
        character.islower() or character.isdigit() or character == "_" for character in value
    )


def _validate_acyclic_dependencies(branches: tuple[ExecutionBranch, ...]) -> None:
    dependencies = {branch.branch_id: branch.depends_on for branch in branches}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(branch_id: str) -> None:
        if branch_id in visiting:
            raise ValueError("Execution branch dependencies must be acyclic.")
        if branch_id in visited:
            return
        visiting.add(branch_id)
        for dependency in dependencies[branch_id]:
            visit(dependency)
        visiting.remove(branch_id)
        visited.add(branch_id)

    for branch_id in dependencies:
        visit(branch_id)
