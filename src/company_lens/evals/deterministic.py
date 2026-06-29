from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from company_lens.evals.golden import (
    CompanyResolutionStatus,
    CompanyTargetSource,
    ExpectedCompany,
    ExpectedRoute,
    ExpectedTool,
    GoldenDataset,
    GoldenDatasetCase,
    load_golden_dataset,
)

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
TRAJECTORY_STATUS = Literal["started", "completed", "failed", "skipped"]
GATE_COMPARATOR = Literal["minimum", "maximum"]


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


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
    status: TRAJECTORY_STATUS = "completed"

    @field_validator("node")
    @classmethod
    def normalize_node(cls, value: str) -> str:
        cleaned = value.strip()
        if not re.fullmatch(r"[a-z][a-z0-9_]*", cleaned):
            raise ValueError("node must use lowercase snake_case")
        return cleaned


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
        return _unique_identifier_values(values)

    @field_validator("operation")
    @classmethod
    def normalize_operation(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            return None
        if not re.fullmatch(r"[a-z][a-z0-9_]*", cleaned):
            raise ValueError("operation must use lowercase snake_case")
        return cleaned

    @field_validator("tools")
    @classmethod
    def validate_unique_tools(cls, values: tuple[ExpectedTool, ...]) -> tuple[ExpectedTool, ...]:
        return _unique_values(values)


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


class RegressionGateFailure(EvaluationModel):
    metric: str
    comparator: GATE_COMPARATOR
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


class RegressionGate(EvaluationModel):
    name: str = Field(min_length=1)
    version: int = Field(ge=1)
    minimums: dict[str, float] = Field(default_factory=dict)
    maximums: dict[str, float] = Field(default_factory=dict)
    require_operational_metrics: bool = False
    operational_budgets: OperationalBudget = Field(default_factory=OperationalBudget)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return _clean_text(value)

    @field_validator("minimums", "maximums")
    @classmethod
    def validate_thresholds(cls, values: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(values) - METRIC_NAMES)
        if unknown:
            raise ValueError(f"unknown metric thresholds: {', '.join(unknown)}")
        out_of_range = [name for name, value in values.items() if value < 0 or value > 1]
        if out_of_range:
            formatted = ", ".join(out_of_range)
            raise ValueError(f"metric thresholds must be between 0 and 1: {formatted}")
        return dict(sorted(values.items()))


class RegressionGateResult(EvaluationModel):
    name: str
    version: int
    passed: bool
    failures: tuple[RegressionGateFailure, ...] = ()


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
    gate: RegressionGateResult | None = None


def load_observed_results(path: Path) -> ObservedGoldenResults:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Observed results must be a JSON object.")
    return ObservedGoldenResults.model_validate(payload)


def load_regression_gate(path: Path) -> RegressionGate:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Regression gate must be a YAML mapping.")
    return RegressionGate.model_validate(payload)


def evaluate_golden_results(
    dataset_path: Path,
    results_path: Path,
    *,
    gate: RegressionGate | None = None,
) -> DeterministicEvaluationReport:
    dataset = load_golden_dataset(dataset_path)
    observed = load_observed_results(results_path)
    return evaluate_dataset(dataset, observed, gate=gate)


def evaluate_dataset(
    dataset: GoldenDataset,
    observed: ObservedGoldenResults,
    *,
    gate: RegressionGate | None = None,
) -> DeterministicEvaluationReport:
    _validate_dataset_identity(dataset, observed)
    observed_by_case = {result.case_id: result for result in observed.results}
    expected_case_ids = {case.id for case in dataset.cases}
    extra_results = tuple(sorted(set(observed_by_case) - expected_case_ids))

    case_reports = tuple(
        _evaluate_case(case, observed_by_case.get(case.id), gate=gate) for case in dataset.cases
    )
    metrics = _evaluation_metrics(dataset.cases, case_reports, observed_by_case)
    passed_cases = sum(1 for case_report in case_reports if case_report.passed)
    report = DeterministicEvaluationReport(
        dataset_name=dataset.name,
        dataset_version=dataset.version,
        passed=passed_cases == len(dataset.cases),
        total_cases=len(dataset.cases),
        evaluated_cases=len(dataset.cases) - len(_missing_results(case_reports)),
        passed_cases=passed_cases,
        failed_cases=len(dataset.cases) - passed_cases,
        missing_results=_missing_results(case_reports),
        extra_results=extra_results,
        metrics=metrics,
        categories=_category_evaluations(case_reports),
        cases=case_reports,
    )
    if gate is None:
        return report
    gate_result = _evaluate_gate(report.metrics, gate)
    return report.model_copy(
        update={
            "passed": report.passed and gate_result.passed,
            "gate": gate_result,
        }
    )


def format_markdown_report(report: DeterministicEvaluationReport) -> str:
    lines = [
        "# Deterministic Evaluation Report",
        "",
        f"- Dataset: `{report.dataset_name}` v{report.dataset_version}",
        f"- Passed: `{str(report.passed).lower()}`",
        f"- Cases: {report.passed_cases}/{report.total_cases}",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for metric, value in report.metrics.model_dump().items():
        lines.append(f"| `{metric}` | {value:.3f} |")
    lines.extend(
        [
            "",
            "## Categories",
            "",
            "| Category | Passed | Total | Pass rate |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for category in report.categories:
        lines.append(
            f"| `{category.category}` | {category.passed} | {category.cases} | "
            f"{category.pass_rate:.3f} |"
        )
    failed_cases = [case for case in report.cases if not case.passed]
    if failed_cases:
        lines.extend(["", "## Failures", ""])
        for case in failed_cases:
            failures = "; ".join(case.failures)
            lines.append(f"- `{case.case_id}` (`{case.category}`): {failures}")
    if report.gate is not None and report.gate.failures:
        lines.extend(["", "## Gate Failures", ""])
        for failure in report.gate.failures:
            lines.append(
                f"- `{failure.metric}` {failure.comparator} {failure.threshold:.3f}; "
                f"actual {failure.actual:.3f}"
            )
    return "\n".join(lines)


def _validate_dataset_identity(dataset: GoldenDataset, observed: ObservedGoldenResults) -> None:
    if observed.dataset_name is not None and observed.dataset_name != dataset.name:
        raise ValueError(
            f"observed results target {observed.dataset_name}, not dataset {dataset.name}"
        )
    if observed.dataset_version is not None and observed.dataset_version != dataset.version:
        raise ValueError(
            f"observed results target dataset version {observed.dataset_version}, "
            f"not version {dataset.version}"
        )


def _evaluate_case(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult | None,
    *,
    gate: RegressionGate | None,
) -> CaseEvaluation:
    if observed is None:
        checks = _missing_case_checks(case)
        return CaseEvaluation(
            case_id=case.id,
            category=case.category,
            passed=False,
            checks=checks,
            failures=("missing observed result",),
        )

    failures: list[str] = []
    checks = {
        "companies": _check_companies(case, observed, failures),
        "metrics": _check_metrics(case, observed, failures),
        "operation": _check_operation(case, observed, failures),
        "route": _check_route(case, observed, failures),
        "required_tools": _check_required_tools(case, observed, failures),
        "prohibited_tools": _check_prohibited_tools(case, observed, failures),
    }
    if case.expected.follow_up is not None:
        checks["follow_up_safety"] = _check_follow_up(case, observed, failures)
    if _operational_checks_enabled(observed, gate):
        checks["operational_budgets"] = _check_operational_budgets(observed, gate, failures)

    return CaseEvaluation(
        case_id=case.id,
        category=case.category,
        passed=all(checks.values()),
        checks=checks,
        failures=tuple(failures),
    )


def _check_companies(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult,
    failures: list[str],
) -> bool:
    passed = True
    matched_observed_indexes: set[int] = set()
    for expected in case.expected.companies:
        actual_index, actual = _find_observed_company(expected, observed.companies)
        if actual is None:
            failures.append(f"missing company target {expected.mention}")
            passed = False
            continue
        matched_observed_indexes.add(actual_index)
        if actual.status != expected.status:
            failures.append(
                f"company {expected.mention} status was {actual.status}, expected {expected.status}"
            )
            passed = False
        if expected.source != actual.source:
            failures.append(
                f"company {expected.mention} source was {actual.source}, expected {expected.source}"
            )
            passed = False

    unexpected = sorted(
        _observed_company_display_key(company)
        for index, company in enumerate(observed.companies)
        if index not in matched_observed_indexes
    )
    if unexpected:
        failures.append(f"unexpected company targets: {', '.join(unexpected)}")
        passed = False
    return passed


def _check_metrics(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult,
    failures: list[str],
) -> bool:
    expected = set(case.expected.metrics)
    actual = set(observed.metrics)
    if actual == expected:
        return True
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing:
        failures.append(f"missing metrics: {', '.join(missing)}")
    if unexpected:
        failures.append(f"unexpected metrics: {', '.join(unexpected)}")
    return False


def _check_operation(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult,
    failures: list[str],
) -> bool:
    if observed.operation == case.expected.operation:
        return True
    failures.append(f"operation was {observed.operation}, expected {case.expected.operation}")
    return False


def _check_route(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult,
    failures: list[str],
) -> bool:
    expected_route = case.expected.route.expected_route
    if observed.route == expected_route:
        return True
    failures.append(f"route was {observed.route}, expected {expected_route}")
    return False


def _check_required_tools(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult,
    failures: list[str],
) -> bool:
    executed_steps = _executed_steps(observed)
    required_tools: set[str] = set(case.expected.route.required_tools)
    missing = sorted(required_tools - executed_steps)
    if not missing:
        return True
    failures.append(f"missing required tools: {', '.join(missing)}")
    return False


def _check_prohibited_tools(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult,
    failures: list[str],
) -> bool:
    executed_steps = _executed_steps(observed)
    prohibited_tools: set[str] = set(case.expected.route.prohibited_tools)
    used = sorted(prohibited_tools & executed_steps)
    if not used:
        return True
    failures.append(f"used prohibited tools: {', '.join(used)}")
    return False


def _check_follow_up(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult,
    failures: list[str],
) -> bool:
    follow_up = case.expected.follow_up
    if follow_up is None:
        return True

    passed = True
    observed_mentions = {_normalize_key(company.mention) for company in observed.companies}

    # Follow-up checks guard the risky path where old conversation state can override a new target.
    prohibited = {_normalize_key(company) for company in follow_up.prohibited_companies}
    reused = sorted(prohibited & observed_mentions)
    if reused:
        failures.append(f"reused prohibited follow-up companies: {', '.join(reused)}")
        passed = False

    blocked_terms = {_normalize_key(term) for term in follow_up.must_not_resolve_terms_as_company}
    resolved_terms = sorted(blocked_terms & observed_mentions)
    if resolved_terms:
        failures.append(f"resolved non-company terms as companies: {', '.join(resolved_terms)}")
        passed = False

    added = {_normalize_key(company) for company in follow_up.add_companies}
    missing_added = sorted(added - observed_mentions)
    if missing_added:
        failures.append(f"missing added follow-up companies: {', '.join(missing_added)}")
        passed = False

    if follow_up.replace_companies is not None:
        replaced_from = {_normalize_key(company) for company in follow_up.replace_companies.from_}
        replaced_to = {_normalize_key(company) for company in follow_up.replace_companies.to}
        still_present = sorted(replaced_from & observed_mentions)
        missing_replacements = sorted(replaced_to - observed_mentions)
        if still_present:
            failures.append(f"kept replaced follow-up companies: {', '.join(still_present)}")
            passed = False
        if missing_replacements:
            failures.append(
                f"missing replacement follow-up companies: {', '.join(missing_replacements)}"
            )
            passed = False

    missing = sorted(
        expected.mention
        for expected in case.expected.companies
        if _find_observed_company(expected, observed.companies)[1] is None
    )
    if missing:
        failures.append(f"missing expected follow-up targets: {', '.join(missing)}")
        passed = False

    return passed


def _missing_case_checks(case: GoldenDatasetCase) -> dict[str, bool]:
    checks = {
        "result_present": False,
        "companies": False,
        "metrics": False,
        "operation": False,
        "route": False,
        "required_tools": not case.expected.route.required_tools,
        "prohibited_tools": not case.expected.route.prohibited_tools,
    }
    if case.expected.follow_up is not None:
        checks["follow_up_safety"] = False
    return checks


def _operational_checks_enabled(
    observed: ObservedCaseResult,
    gate: RegressionGate | None,
) -> bool:
    if observed.operational is not None:
        return True
    return bool(
        gate is not None
        and (gate.require_operational_metrics or gate.operational_budgets.configured())
    )


def _check_operational_budgets(
    observed: ObservedCaseResult,
    gate: RegressionGate | None,
    failures: list[str],
) -> bool:
    operational = observed.operational
    if operational is None:
        failures.append("missing operational metrics")
        return False

    passed = True
    budget = gate.operational_budgets if gate is not None else OperationalBudget()
    passed &= _check_maximum(
        "total latency",
        operational.total_latency_ms,
        budget.max_total_latency_ms,
        "ms",
        failures,
    )
    passed &= _check_maximum(
        "time to first event",
        operational.time_to_first_event_ms,
        budget.max_time_to_first_event_ms,
        "ms",
        failures,
    )
    passed &= _check_maximum(
        "tool calls",
        operational.tool_calls_used,
        _explicit_or_policy(budget.max_tool_calls, operational.policy_max_tool_calls),
        "",
        failures,
    )
    passed &= _check_maximum(
        "repair attempts",
        operational.repair_attempts,
        _explicit_or_policy(
            budget.max_repair_attempts,
            operational.policy_max_repair_attempts,
        ),
        "",
        failures,
    )
    passed &= _check_maximum(
        "API calls",
        operational.api_calls,
        budget.max_api_calls,
        "",
        failures,
    )
    passed &= _check_maximum(
        "retry count",
        operational.retry_count,
        budget.max_retry_count,
        "",
        failures,
    )
    passed &= _check_maximum(
        "total tokens",
        operational.total_tokens,
        budget.max_total_tokens,
        "",
        failures,
    )
    passed &= _check_maximum(
        "cost",
        operational.cost_usd,
        budget.max_cost_usd,
        " USD",
        failures,
    )
    if budget.max_node_latency_ms is not None:
        if not operational.node_latencies:
            failures.append("missing node latency metrics")
            passed = False
        for item in operational.node_latencies:
            passed &= _check_maximum(
                f"node {item.node} latency",
                item.duration_ms,
                budget.max_node_latency_ms,
                "ms",
                failures,
            )
    if operational.policy_max_retries_per_node is not None:
        for attempt in operational.node_attempts:
            allowed_attempts = operational.policy_max_retries_per_node + 1
            if attempt.attempts > allowed_attempts:
                failures.append(
                    f"node {attempt.node} attempts were {attempt.attempts}, "
                    f"expected at most {allowed_attempts}"
                )
                passed = False
    return passed


def _check_maximum(
    label: str,
    actual: int | float | None,
    maximum: int | float | None,
    unit: str,
    failures: list[str],
) -> bool:
    if maximum is None:
        return True
    if actual is None:
        failures.append(f"missing {label} metric")
        return False
    if actual <= maximum:
        return True
    failures.append(f"{label} was {actual}{unit}, expected at most {maximum}{unit}")
    return False


def _explicit_or_policy(
    explicit: int | float | None,
    policy: int | float | None,
) -> int | float | None:
    return explicit if explicit is not None else policy


def _evaluation_metrics(
    cases: tuple[GoldenDatasetCase, ...],
    reports: tuple[CaseEvaluation, ...],
    observed_by_case: dict[str, ObservedCaseResult],
) -> EvaluationMetrics:
    report_by_case = {report.case_id: report for report in reports}
    required_hits = 0
    required_total = 0
    prohibited_clean = 0
    prohibited_total = 0
    follow_up_reports = []
    for case in cases:
        report = report_by_case[case.id]
        if report.checks.get("follow_up_safety") is not None:
            follow_up_reports.append(report)

    for case in cases:
        observed = observed_by_case.get(case.id)
        expected_required: set[str] = set(case.expected.route.required_tools)
        expected_prohibited: set[str] = set(case.expected.route.prohibited_tools)
        required_total += len(expected_required)
        prohibited_total += len(expected_prohibited)
        if observed is None:
            continue
        executed_steps = _executed_steps(observed)
        required_hits += len(expected_required & executed_steps)
        prohibited_clean += len(expected_prohibited - executed_steps)

    total_cases = len(cases)
    missing = sum(1 for report in reports if report.checks.get("result_present") is False)
    return EvaluationMetrics(
        case_pass_rate=_ratio(sum(1 for report in reports if report.passed), total_cases),
        company_accuracy=_check_ratio(reports, "companies"),
        metric_accuracy=_check_ratio(reports, "metrics"),
        operation_accuracy=_check_ratio(reports, "operation"),
        route_accuracy=_check_ratio(reports, "route"),
        required_tool_recall=_ratio(required_hits, required_total),
        prohibited_tool_pass_rate=_ratio(prohibited_clean, prohibited_total),
        follow_up_safety_accuracy=_check_ratio(follow_up_reports, "follow_up_safety"),
        operational_metrics_presence_rate=_ratio(
            sum(
                1
                for case in cases
                if (result := observed_by_case.get(case.id)) is not None
                and result.operational is not None
            ),
            len(cases),
        ),
        operational_budget_pass_rate=_check_ratio(reports, "operational_budgets"),
        missing_result_rate=_ratio(missing, total_cases),
    )


def _category_evaluations(reports: tuple[CaseEvaluation, ...]) -> tuple[CategoryEvaluation, ...]:
    categories = tuple(dict.fromkeys(report.category for report in reports))
    rows: list[CategoryEvaluation] = []
    for category in categories:
        category_reports = [report for report in reports if report.category == category]
        passed = sum(1 for report in category_reports if report.passed)
        rows.append(
            CategoryEvaluation(
                category=category,
                cases=len(category_reports),
                passed=passed,
                failed=len(category_reports) - passed,
                pass_rate=_ratio(passed, len(category_reports)),
            )
        )
    return tuple(rows)


def _evaluate_gate(metrics: EvaluationMetrics, gate: RegressionGate) -> RegressionGateResult:
    metric_values = metrics.model_dump()
    failures: list[RegressionGateFailure] = []
    for metric, threshold in gate.minimums.items():
        actual = float(metric_values[metric])
        if actual < threshold:
            failures.append(
                RegressionGateFailure(
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
                RegressionGateFailure(
                    metric=metric,
                    comparator="maximum",
                    threshold=threshold,
                    actual=actual,
                )
            )
    return RegressionGateResult(
        name=gate.name,
        version=gate.version,
        passed=not failures,
        failures=tuple(failures),
    )


def _missing_results(reports: tuple[CaseEvaluation, ...]) -> tuple[str, ...]:
    return tuple(
        report.case_id for report in reports if report.checks.get("result_present") is False
    )


def _check_ratio(reports: tuple[CaseEvaluation, ...] | list[CaseEvaluation], check: str) -> float:
    applicable = [report for report in reports if check in report.checks]
    return _ratio(sum(1 for report in applicable if report.checks[check]), len(applicable))


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 1.0
    return round(numerator / denominator, 6)


def _executed_steps(observed: ObservedCaseResult) -> set[str]:
    steps: set[str] = set(observed.tools)
    steps.update(event.node for event in observed.trajectory if event.status != "skipped")
    return steps


def _find_observed_company(
    expected: ExpectedCompany,
    observed_companies: tuple[ObservedCompany, ...],
) -> tuple[int, ObservedCompany | None]:
    expected_keys = _expected_company_keys(expected)
    candidates = [
        (index, observed)
        for index, observed in enumerate(observed_companies)
        if expected_keys & _observed_company_keys(observed)
    ]
    for index, observed in candidates:
        # Prefer the candidate that already satisfies status/source so duplicate mentions
        # still surface the extra unmatched company as unexpected.
        if observed.status == expected.status and observed.source == expected.source:
            return index, observed
    return candidates[0] if candidates else (-1, None)


def _expected_company_keys(company: ExpectedCompany) -> set[str]:
    keys = {_normalize_key(company.mention)}
    if company.ticker:
        keys.add(_normalize_key(company.ticker))
    return keys


def _observed_company_keys(company: ObservedCompany) -> set[str]:
    keys = {_normalize_key(company.mention)}
    if company.ticker:
        keys.add(_normalize_key(company.ticker))
    return keys


def _observed_company_display_key(company: ObservedCompany) -> str:
    if company.ticker:
        return _normalize_key(company.ticker)
    return _normalize_key(company.mention)


def _normalize_key(value: str) -> str:
    return _clean_text(value).casefold()


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


def _unique_values[ValueT](values: tuple[ValueT, ...]) -> tuple[ValueT, ...]:
    return tuple(dict.fromkeys(values))


def _unique_cleaned(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_clean_text(value) for value in values))


def _unique_identifier_values(values: tuple[str, ...]) -> tuple[str, ...]:
    cleaned = _unique_cleaned(values)
    invalid = [value for value in cleaned if not re.fullmatch(r"[a-z][a-z0-9_]*", value)]
    if invalid:
        formatted = ", ".join(invalid)
        raise ValueError(f"values must use lowercase snake_case identifiers: {formatted}")
    return cleaned
