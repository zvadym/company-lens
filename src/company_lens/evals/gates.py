from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, field_validator

from company_lens.evals.models import EvaluationMetrics, EvaluationModel

METRIC_NAMES = frozenset(
    {
        "case_pass_rate",
        "company_accuracy",
        "metric_accuracy",
        "operation_accuracy",
        "route_accuracy",
        "required_tool_recall",
        "prohibited_tool_pass_rate",
        "follow_up_safety_accuracy",
        "operational_metrics_presence_rate",
        "operational_budget_pass_rate",
        "missing_result_rate",
    }
)
GateComparator = Literal["minimum", "maximum"]


class EvaluationGateFailure(EvaluationModel):
    metric: str
    comparator: GateComparator
    threshold: float
    actual: float


class OperationalBudget(EvaluationModel):
    max_total_latency_ms: int | None = Field(default=None, ge=0)
    max_time_to_first_event_ms: int | None = Field(default=None, ge=0)
    max_node_latency_ms: int | None = Field(default=None, ge=0)
    max_tool_calls: int | None = Field(default=None, ge=0)
    max_repair_attempts: int | None = Field(default=None, ge=0)
    max_api_calls: int | None = Field(default=None, ge=0)
    max_retry_count: int | None = Field(default=None, ge=0)
    max_total_tokens: int | None = Field(default=None, ge=0)
    max_cost_usd: float | None = Field(default=None, ge=0)

    def configured(self) -> bool:
        return any(value is not None for value in self.model_dump().values())


class EvaluationGate(EvaluationModel):
    name: str = Field(min_length=1)
    version: int = Field(ge=1)
    minimums: dict[str, float] = Field(default_factory=dict)
    maximums: dict[str, float] = Field(default_factory=dict)
    require_operational_metrics: bool = False
    operational_budgets: OperationalBudget = Field(default_factory=OperationalBudget)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("text values cannot be blank")
        return cleaned

    @field_validator("minimums", "maximums")
    @classmethod
    def validate_thresholds(cls, values: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(values) - METRIC_NAMES)
        if unknown:
            raise ValueError(f"unknown metric thresholds: {', '.join(unknown)}")
        out_of_range = [name for name, value in values.items() if value < 0 or value > 1]
        if out_of_range:
            raise ValueError(
                "metric thresholds must be between 0 and 1: " + ", ".join(out_of_range)
            )
        return dict(sorted(values.items()))


class EvaluationGateResult(EvaluationModel):
    name: str
    version: int
    passed: bool
    failures: tuple[EvaluationGateFailure, ...] = ()


def load_evaluation_gate(path: Path) -> EvaluationGate:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Evaluation gate must be a YAML mapping.")
    return EvaluationGate.model_validate(payload)


def evaluate_gate(metrics: EvaluationMetrics, gate: EvaluationGate) -> EvaluationGateResult:
    metric_values = metrics.model_dump()
    failures: list[EvaluationGateFailure] = []
    for metric, threshold in gate.minimums.items():
        actual = float(metric_values[metric])
        if actual < threshold:
            failures.append(
                EvaluationGateFailure(
                    metric=metric,
                    comparator="minimum",
                    threshold=threshold,
                    actual=actual,
                )
            )
    for metric, threshold in gate.maximums.items():
        actual = float(metric_values[metric])
        if actual > threshold:
            failures.append(
                EvaluationGateFailure(
                    metric=metric,
                    comparator="maximum",
                    threshold=threshold,
                    actual=actual,
                )
            )
    return EvaluationGateResult(
        name=gate.name,
        version=gate.version,
        passed=not failures,
        failures=tuple(failures),
    )


# Compatibility aliases retained for callers of the feature-002 API.
RegressionGate = EvaluationGate
RegressionGateFailure = EvaluationGateFailure
RegressionGateResult = EvaluationGateResult
load_regression_gate = load_evaluation_gate
