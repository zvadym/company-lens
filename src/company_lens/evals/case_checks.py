from __future__ import annotations

from company_lens.evals.company_matching import (
    find_observed_company,
    observed_company_display_key,
)
from company_lens.evals.follow_up_checks import check_follow_up
from company_lens.evals.gates import EvaluationGate
from company_lens.evals.golden import GoldenDatasetCase
from company_lens.evals.models import CaseEvaluation, ObservedCaseResult
from company_lens.evals.operational_checks import (
    check_operational_budgets,
    operational_checks_enabled,
)


def evaluate_case(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult | None,
    *,
    gate: EvaluationGate | None,
) -> CaseEvaluation:
    if observed is None:
        return CaseEvaluation(
            case_id=case.id,
            category=case.category,
            passed=False,
            checks=_missing_case_checks(case),
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
        checks["follow_up_safety"] = check_follow_up(case, observed, failures)
    if operational_checks_enabled(observed, gate):
        checks["operational_budgets"] = check_operational_budgets(observed, gate, failures)

    return CaseEvaluation(
        case_id=case.id,
        category=case.category,
        passed=all(checks.values()),
        checks=checks,
        failures=tuple(failures),
    )


def executed_steps(observed: ObservedCaseResult) -> set[str]:
    steps: set[str] = set(observed.tools)
    steps.update(event.node for event in observed.trajectory if event.status != "skipped")
    return steps


def _check_companies(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult,
    failures: list[str],
) -> bool:
    passed = True
    matched_indexes: set[int] = set()
    for expected in case.expected.companies:
        actual_index, actual = find_observed_company(expected, observed.companies)
        if actual is None:
            failures.append(f"missing company target {expected.mention}")
            passed = False
            continue
        matched_indexes.add(actual_index)
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
        observed_company_display_key(company)
        for index, company in enumerate(observed.companies)
        if index not in matched_indexes
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
    required: set[str] = set(case.expected.route.required_tools)
    missing = sorted(required - executed_steps(observed))
    if not missing:
        return True
    failures.append(f"missing required tools: {', '.join(missing)}")
    return False


def _check_prohibited_tools(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult,
    failures: list[str],
) -> bool:
    used = sorted(set(case.expected.route.prohibited_tools) & executed_steps(observed))
    if not used:
        return True
    failures.append(f"used prohibited tools: {', '.join(used)}")
    return False


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
