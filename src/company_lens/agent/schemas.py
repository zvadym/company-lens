from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Annotated, Literal, NotRequired, Required, TypedDict

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from company_lens.analytics.schemas import CalculationResult, ChartSpecification
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


class EvidenceKind(enum.StrEnum):
    DOCUMENT = "document"
    FINANCIAL_FACT = "financial_fact"
    MACRO_OBSERVATION = "macro_observation"
    CALCULATION = "calculation"


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


class ChartBranch(BranchBase):
    kind: Literal["generate_chart_spec"] = "generate_chart_spec"
    chart_type: Literal["line", "bar", "area", "scatter"]
    dataset_ref: str = Field(min_length=1)


ExecutionBranch = Annotated[
    DocumentRetrievalBranch
    | FinancialFactsBranch
    | MacroSeriesBranch
    | CalculationBranch
    | ChartBranch,
    Field(discriminator="kind"),
]


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


class EvidenceEnvelope(FrozenModel):
    evidence_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]*$")
    kind: EvidenceKind
    summary: str = Field(min_length=1)
    source_urls: tuple[str, ...] = ()
    lineage_refs: tuple[str, ...] = ()
    payload: dict[str, object] = Field(default_factory=dict)


class CitationReference(FrozenModel):
    evidence_id: str = Field(min_length=1)
    label: str = Field(min_length=1)


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


class AgentState(TypedDict, total=False):
    run_id: Required[uuid.UUID]
    session_id: Required[str]
    question: Required[str]
    policy: Required[ExecutionPolicy]
    status: Required[AgentRunStatus]
    messages: Required[tuple[SessionMessage, ...]]
    analysis: NotRequired[QuestionAnalysis]
    resolved_query: NotRequired[ResolvedQuery]
    execution_plan: NotRequired[ExecutionPlan]
    retrieval_results: NotRequired[tuple[AdaptiveRetrievalResponse, ...]]
    financial_results: NotRequired[tuple[FinancialFactQueryResult, ...]]
    macro_results: NotRequired[tuple[FredSeriesResult, ...]]
    calculations: NotRequired[tuple[CalculationResult, ...]]
    evidence: NotRequired[tuple[EvidenceEnvelope, ...]]
    chart_spec: NotRequired[ChartSpecification | None]
    draft_answer: NotRequired[str | None]
    final_answer: NotRequired[str | None]
    citations: NotRequired[tuple[CitationReference, ...]]
    errors: NotRequired[tuple[AgentError, ...]]
    trajectory: NotRequired[tuple[TrajectoryEvent, ...]]
    node_attempts: NotRequired[tuple[NodeAttempt, ...]]
    tool_calls_used: NotRequired[int]


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
