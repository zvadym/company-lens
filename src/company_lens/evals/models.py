from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from company_lens.evals.golden import (
    CitationMode,
    CompanyResolutionStatus,
    CompanyTargetSource,
    ExpectedRoute,
    ExpectedTool,
)
from company_lens.evals.manifest import (
    ComponentVersions,
    DatasetSnapshot,
    EvaluationRunManifest,
    ExecutionPolicyManifest,
    GateManifest,
    LangfuseProjectIdentity,
    ManifestDataset,
    ModelConfigManifest,
    PromptVersionManifest,
    ScoreConfigBinding,
    ScoreContractManifest,
    WorkflowMetadata,
)


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


TrajectoryStatus = Literal["started", "completed", "failed", "skipped"]


class ObservedCompany(EvaluationModel):
    mention: str = Field(min_length=1)
    status: CompanyResolutionStatus
    ticker: str | None = None
    source: CompanyTargetSource | None = None

    @field_validator("mention")
    @classmethod
    def normalize_mention(cls, value: str) -> str:
        return _clean_text(value)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str | None) -> str | None:
        if value is None:
            return None
        ticker = value.strip().upper().removeprefix("$")
        if not ticker:
            return None
        if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,15}", ticker):
            raise ValueError("ticker must be a concise market symbol")
        return ticker


class ObservedTrajectoryEvent(EvaluationModel):
    node: str = Field(min_length=1)
    status: TrajectoryStatus = "completed"

    @field_validator("node")
    @classmethod
    def normalize_node(cls, value: str) -> str:
        return _clean_identifier(value, field_name="node")


class ObservedNodeLatency(EvaluationModel):
    node: str = Field(min_length=1)
    duration_ms: int = Field(ge=0)

    @field_validator("node")
    @classmethod
    def normalize_node(cls, value: str) -> str:
        return _clean_identifier(value, field_name="node")


class ObservedNodeAttempt(EvaluationModel):
    node: str = Field(min_length=1)
    attempts: int = Field(ge=1)

    @field_validator("node")
    @classmethod
    def normalize_node(cls, value: str) -> str:
        return _clean_identifier(value, field_name="node")


class ObservedOperationalMetrics(EvaluationModel):
    total_latency_ms: int | None = Field(default=None, ge=0)
    time_to_first_event_ms: int | None = Field(default=None, ge=0)
    node_latencies: tuple[ObservedNodeLatency, ...] = ()
    tool_calls_used: int | None = Field(default=None, ge=0)
    repair_attempts: int | None = Field(default=None, ge=0)
    api_calls: int | None = Field(default=None, ge=0)
    retry_count: int | None = Field(default=None, ge=0)
    node_attempts: tuple[ObservedNodeAttempt, ...] = ()
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    policy_max_tool_calls: int | None = Field(default=None, ge=1)
    policy_max_repair_attempts: int | None = Field(default=None, ge=0)
    policy_max_retries_per_node: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_token_total(self) -> ObservedOperationalMetrics:
        if (
            self.input_tokens is not None
            and self.output_tokens is not None
            and self.total_tokens is not None
            and self.total_tokens != self.input_tokens + self.output_tokens
        ):
            raise ValueError("total_tokens must equal input_tokens plus output_tokens")
        return self


class ObservedCaseResult(EvaluationModel):
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]*_[0-9]{3}$")
    companies: tuple[ObservedCompany, ...] = ()
    metrics: tuple[str, ...] = ()
    operation: str | None = None
    route: ExpectedRoute | None = None
    tools: tuple[ExpectedTool, ...] = ()
    trajectory: tuple[ObservedTrajectoryEvent, ...] = ()
    operational: ObservedOperationalMetrics | None = None

    @field_validator("metrics")
    @classmethod
    def normalize_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(dict.fromkeys(_clean_text(value) for value in values))
        invalid = [value for value in cleaned if not re.fullmatch(r"[a-z][a-z0-9_]*", value)]
        if invalid:
            raise ValueError(
                f"values must use lowercase snake_case identifiers: {', '.join(invalid)}"
            )
        return cleaned

    @field_validator("operation")
    @classmethod
    def normalize_operation(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        return _clean_identifier(value, field_name="operation")

    @field_validator("tools")
    @classmethod
    def validate_unique_tools(cls, values: tuple[ExpectedTool, ...]) -> tuple[ExpectedTool, ...]:
        return tuple(dict.fromkeys(values))


class ObservedGoldenResults(EvaluationModel):
    schema_version: int = Field(default=1, ge=1)
    dataset_name: str | None = None
    dataset_version: int | None = Field(default=None, ge=1)
    results: tuple[ObservedCaseResult, ...] = Field(min_length=1)

    @field_validator("dataset_name")
    @classmethod
    def normalize_dataset_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not re.fullmatch(r"[a-z][a-z0-9\-]*", cleaned):
            raise ValueError("dataset_name must match the golden dataset name format")
        return cleaned

    @model_validator(mode="after")
    def validate_unique_results(self) -> ObservedGoldenResults:
        case_ids = [result.case_id for result in self.results]
        duplicates = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate observed results: {', '.join(duplicates)}")
        return self


class EvaluationMetrics(EvaluationModel):
    case_pass_rate: float
    company_accuracy: float
    metric_accuracy: float
    operation_accuracy: float
    route_accuracy: float
    required_tool_recall: float
    prohibited_tool_pass_rate: float
    follow_up_safety_accuracy: float
    operational_metrics_presence_rate: float
    operational_budget_pass_rate: float
    missing_result_rate: float


class CategoryEvaluation(EvaluationModel):
    category: str
    cases: int
    passed: int
    failed: int
    pass_rate: float


class CaseEvaluation(EvaluationModel):
    case_id: str
    category: str
    passed: bool
    checks: dict[str, bool]
    failures: tuple[str, ...] = ()


class DeterministicEvaluationReport(EvaluationModel):
    dataset_name: str
    dataset_version: int
    passed: bool
    total_cases: int
    evaluated_cases: int
    passed_cases: int
    failed_cases: int
    missing_results: tuple[str, ...]
    extra_results: tuple[str, ...]
    metrics: EvaluationMetrics
    categories: tuple[CategoryEvaluation, ...]
    cases: tuple[CaseEvaluation, ...]
    gate: Any | None = None


class CitationObservation(EvaluationModel):
    mode: CitationMode
    answer_present: bool
    validation_present: bool
    valid: bool | None = None
    claim_count: int = Field(default=0, ge=0)
    cited_evidence_count: int = Field(default=0, ge=0)
    unknown_evidence_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_citation_state(self) -> CitationObservation:
        if self.mode == "not_applicable" and self.valid is not None:
            raise ValueError("not-applicable citation cannot have a validity verdict")
        if not self.validation_present and self.valid is not None and self.answer_present:
            raise ValueError("citation verdict requires validation output")
        if len(set(self.unknown_evidence_ids)) != len(self.unknown_evidence_ids):
            raise ValueError("unknown evidence IDs must be unique")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("citation reason codes must be unique")
        return self


class CaseObservation(EvaluationModel):
    case_id: str = Field(pattern=r"^[a-z][a-z0-9_]*_[0-9]{3}$")
    outcome: Literal["observed", "infrastructure_error"]
    failure_code: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_]*$")
    companies: tuple[ObservedCompany, ...] = ()
    metrics: tuple[str, ...] = ()
    operation: str | None = None
    route: ExpectedRoute | None = None
    tools: tuple[ExpectedTool, ...] = ()
    trajectory: tuple[ObservedTrajectoryEvent, ...] = ()
    operational: ObservedOperationalMetrics | None = None
    citation: CitationObservation

    @model_validator(mode="after")
    def validate_outcome(self) -> CaseObservation:
        if (self.outcome == "infrastructure_error") != (self.failure_code is not None):
            raise ValueError("infrastructure outcomes require exactly one failure code")
        return self


class CaseEvaluationRecord(EvaluationModel):
    case_id: str
    category: str
    passed: bool | None
    checks: dict[str, bool] = Field(default_factory=dict)
    failure_codes: tuple[str, ...] = ()
    scores: dict[str, bool | float | str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_failure_codes(self) -> CaseEvaluationRecord:
        if len(set(self.failure_codes)) != len(self.failure_codes):
            raise ValueError("case failure codes must be unique")
        return self


class CaseIdentity(EvaluationModel):
    dataset_name: str = Field(min_length=1)
    case_id: str = Field(min_length=1)


class ReportingTarget(EvaluationModel):
    repository: str = Field(pattern=r"^[^/\s]+/[^/\s]+$")
    pr_number: int = Field(ge=1)


class DatasetEvaluationRun(EvaluationModel):
    dataset_name: str
    dataset_version: int = Field(ge=1)
    snapshot: DatasetSnapshot | None = None
    status: Literal["completed", "partial", "errored"]
    gate_status: Literal["passed", "failed", "not_evaluated"]
    selected_case_ids: tuple[str, ...] = Field(min_length=1)
    case_results: tuple[CaseEvaluationRecord, ...] = ()
    aggregate_scores: dict[str, float] = Field(default_factory=dict)
    langfuse_dataset_run_id: str | None = None
    langfuse_run_url: str | None = None

    @model_validator(mode="after")
    def validate_state(self) -> DatasetEvaluationRun:
        if self.status == "completed" and self.gate_status == "not_evaluated":
            raise ValueError("completed dataset run requires passed or failed gate")
        if self.status != "completed" and self.gate_status != "not_evaluated":
            raise ValueError("partial or errored dataset run requires not_evaluated gate")
        if len(set(self.selected_case_ids)) != len(self.selected_case_ids):
            raise ValueError("selected case IDs must be unique")
        result_ids = [result.case_id for result in self.case_results]
        if len(set(result_ids)) != len(result_ids):
            raise ValueError("case result IDs must be unique")
        if not set(result_ids).issubset(self.selected_case_ids):
            raise ValueError("case results must belong to selected cases")
        if self.status == "completed" and set(result_ids) != set(self.selected_case_ids):
            raise ValueError("completed dataset run requires one result per selected case")
        if self.status == "completed" and self.snapshot is None:
            raise ValueError("completed dataset run requires a verified snapshot")
        return self


class EvaluationRecoveryJournal(EvaluationModel):
    schema_version: Literal[1] = 1
    execution_id: UUID
    sequence: int = Field(ge=0)
    updated_at: datetime
    project_identity: LangfuseProjectIdentity | None = None
    manifest: EvaluationRunManifest | None = None
    phase: Literal[
        "initialized", "project_verified", "preflighted", "running", "reporting", "terminal"
    ]
    status: Literal["running", "completed", "partial", "errored"]
    gate_status: Literal["pending", "passed", "failed", "not_evaluated"]
    reporting_status: Literal["not_requested", "pending", "succeeded", "failed"]
    reporting_target: ReportingTarget | None = None
    dataset_runs: tuple[DatasetEvaluationRun, ...] = ()
    terminal_cases: tuple[CaseIdentity, ...] = ()
    failure_codes: tuple[str, ...] = ()
    reporting_failure_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_state(self) -> EvaluationRecoveryJournal:
        if self.phase == "terminal" and self.status == "running":
            raise ValueError("terminal phase requires a terminal evaluation status")
        if self.phase == "initialized" and (
            self.project_identity is not None or self.manifest is not None
        ):
            raise ValueError("initialized journal cannot contain preflight state")
        if self.phase == "project_verified" and (
            self.project_identity is None
            or self.project_identity.status != "verified"
            or self.manifest is not None
        ):
            raise ValueError("project-verified phase requires only verified project identity")
        if self.phase in {"preflighted", "running"} and (
            self.project_identity is None
            or self.project_identity.status != "verified"
            or self.manifest is None
            or not self.manifest.replay_ready
        ):
            raise ValueError("execution phase requires a fully verified manifest")
        if self.phase in {"reporting", "terminal"} and (
            self.project_identity is None or self.manifest is None
        ):
            raise ValueError("terminal evaluation state requires frozen preflight identity")
        if self.phase in {"initialized", "project_verified", "preflighted", "running"} and (
            self.status != "running" or self.gate_status != "pending"
        ):
            raise ValueError("nonterminal evaluation phase requires running and pending")
        if self.phase == "reporting" and self.reporting_status != "pending":
            raise ValueError("reporting phase requires pending reporting status")
        if self.phase == "terminal" and self.reporting_status == "pending":
            raise ValueError("terminal phase cannot retain pending reporting status")
        if self.status == "completed" and self.gate_status not in {"passed", "failed"}:
            raise ValueError("completed execution requires passed or failed gate")
        if self.status in {"partial", "errored"} and self.gate_status != "not_evaluated":
            raise ValueError("partial or errored execution requires not_evaluated gate")
        if self.status == "running" and self.gate_status != "pending":
            raise ValueError("running execution requires pending gate")
        if (self.reporting_status == "not_requested") != (self.reporting_target is None):
            raise ValueError("reporting target is required exactly when reporting is requested")
        if self.reporting_status == "failed" and not self.reporting_failure_codes:
            raise ValueError("failed reporting requires a failure code")
        if self.reporting_status != "failed" and self.reporting_failure_codes:
            raise ValueError("reporting failure codes require failed reporting")
        if self.manifest is not None and self.manifest.execution_id != self.execution_id:
            raise ValueError("journal and manifest execution IDs must match")
        dataset_names = [run.dataset_name for run in self.dataset_runs]
        if len(set(dataset_names)) != len(dataset_names):
            raise ValueError("journal dataset runs must be unique")
        if len(set(self.terminal_cases)) != len(self.terminal_cases):
            raise ValueError("journal terminal case identities must be unique")
        if len(set(self.failure_codes)) != len(self.failure_codes):
            raise ValueError("journal failure codes must be unique")
        if len(set(self.reporting_failure_codes)) != len(self.reporting_failure_codes):
            raise ValueError("journal reporting failure codes must be unique")
        return self


class ArtifactPaths(EvaluationModel):
    journal: str
    json_path: str = Field(alias="json", serialization_alias="json")
    markdown: str


class EvaluationExecution(EvaluationModel):
    schema_version: Literal[1] = 1
    execution_id: UUID
    started_at: datetime
    completed_at: datetime
    status: Literal["completed", "partial", "errored"]
    gate_status: Literal["passed", "failed", "not_evaluated"]
    manifest: EvaluationRunManifest
    runs: tuple[DatasetEvaluationRun, ...] = Field(min_length=1)
    failure_codes: tuple[str, ...] = ()
    artifact_paths: ArtifactPaths

    @model_validator(mode="after")
    def validate_execution(self) -> EvaluationExecution:
        if self.completed_at < self.started_at:
            raise ValueError("execution completion cannot precede start")
        if self.status == "completed" and self.gate_status == "not_evaluated":
            raise ValueError("completed execution requires a trusted gate verdict")
        if self.status != "completed" and self.gate_status != "not_evaluated":
            raise ValueError("incomplete execution requires not-evaluated gate")
        if self.manifest.execution_id != self.execution_id:
            raise ValueError("execution and manifest IDs must match")
        run_names = [run.dataset_name for run in self.runs]
        if len(set(run_names)) != len(run_names):
            raise ValueError("execution dataset runs must be unique")
        manifest_names = {dataset.dataset_name for dataset in self.manifest.datasets}
        if set(run_names) != manifest_names:
            raise ValueError("execution requires one run per manifest dataset")
        if len(set(self.failure_codes)) != len(self.failure_codes):
            raise ValueError("execution failure codes must be unique")
        return self


def _clean_identifier(value: str, *, field_name: str) -> str:
    cleaned = value.strip()
    if not re.fullmatch(r"[a-z][a-z0-9_]*", cleaned):
        raise ValueError(f"{field_name} must use lowercase snake_case")
    return cleaned


def _clean_text(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("text values cannot be blank")
    return cleaned


__all__ = [
    "ArtifactPaths",
    "CaseEvaluationRecord",
    "CaseEvaluation",
    "CaseIdentity",
    "CaseObservation",
    "CitationObservation",
    "ComponentVersions",
    "DatasetEvaluationRun",
    "DatasetSnapshot",
    "DeterministicEvaluationReport",
    "EvaluationMetrics",
    "EvaluationExecution",
    "EvaluationRecoveryJournal",
    "EvaluationRunManifest",
    "ExecutionPolicyManifest",
    "GateManifest",
    "LangfuseProjectIdentity",
    "ManifestDataset",
    "ModelConfigManifest",
    "ObservedCaseResult",
    "ObservedCompany",
    "ObservedGoldenResults",
    "ObservedNodeAttempt",
    "ObservedNodeLatency",
    "ObservedOperationalMetrics",
    "ObservedTrajectoryEvent",
    "PromptVersionManifest",
    "ReportingTarget",
    "ScoreConfigBinding",
    "ScoreContractManifest",
    "WorkflowMetadata",
    "CategoryEvaluation",
]
