from __future__ import annotations

from company_lens.evals.gates import EvaluationGate
from company_lens.evals.golden import ExpectedCompany, GoldenDatasetCase
from company_lens.evals.models import CaseEvaluation, ObservedCaseResult, ObservedCompany
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
        checks["follow_up_safety"] = _check_follow_up(case, observed, failures)
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
        actual_index, actual = _find_observed_company(expected, observed.companies)
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
        _observed_company_display_key(company)
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


def _check_follow_up(
    case: GoldenDatasetCase,
    observed: ObservedCaseResult,
    failures: list[str],
) -> bool:
    follow_up = case.expected.follow_up
    if follow_up is None:
        return True

    passed = True
    mentions = {_normalize_key(company.mention) for company in observed.companies}
    reused = sorted({_normalize_key(item) for item in follow_up.prohibited_companies} & mentions)
    if reused:
        failures.append(f"reused prohibited follow-up companies: {', '.join(reused)}")
        passed = False
    resolved_terms = sorted(
        {_normalize_key(item) for item in follow_up.must_not_resolve_terms_as_company} & mentions
    )
    if resolved_terms:
        failures.append(f"resolved non-company terms as companies: {', '.join(resolved_terms)}")
        passed = False
    missing_added = sorted({_normalize_key(item) for item in follow_up.add_companies} - mentions)
    if missing_added:
        failures.append(f"missing added follow-up companies: {', '.join(missing_added)}")
        passed = False
    if follow_up.replace_companies is not None:
        replaced_from = {_normalize_key(item) for item in follow_up.replace_companies.from_}
        replaced_to = {_normalize_key(item) for item in follow_up.replace_companies.to}
        still_present = sorted(replaced_from & mentions)
        missing_replacements = sorted(replaced_to - mentions)
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


def _find_observed_company(
    expected: ExpectedCompany,
    observed_companies: tuple[ObservedCompany, ...],
) -> tuple[int, ObservedCompany | None]:
    expected_keys = {_normalize_key(expected.mention)}
    if expected.ticker:
        expected_keys.add(_normalize_key(expected.ticker))
    candidates = [
        (index, observed)
        for index, observed in enumerate(observed_companies)
        if expected_keys & _observed_company_keys(observed)
    ]
    for index, observed in candidates:
        if observed.status == expected.status and observed.source == expected.source:
            return index, observed
    return candidates[0] if candidates else (-1, None)


def _observed_company_keys(company: ObservedCompany) -> set[str]:
    keys = {_normalize_key(company.mention)}
    if company.ticker:
        keys.add(_normalize_key(company.ticker))
    return keys


def _observed_company_display_key(company: ObservedCompany) -> str:
    return _normalize_key(company.ticker or company.mention)


def _normalize_key(value: str) -> str:
    return " ".join(value.split()).casefold()
