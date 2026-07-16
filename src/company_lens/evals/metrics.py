from __future__ import annotations

from company_lens.evals.case_checks import executed_steps
from company_lens.evals.golden import GoldenDatasetCase
from company_lens.evals.models import (
    CaseEvaluation,
    CategoryEvaluation,
    EvaluationMetrics,
    ObservedCaseResult,
)


def evaluation_metrics(
    cases: tuple[GoldenDatasetCase, ...],
    reports: tuple[CaseEvaluation, ...],
    observed_by_case: dict[str, ObservedCaseResult],
) -> EvaluationMetrics:
    report_by_case = {report.case_id: report for report in reports}
    required_hits = 0
    required_total = 0
    prohibited_clean = 0
    prohibited_total = 0
    follow_up_reports = [
        report_by_case[case.id]
        for case in cases
        if "follow_up_safety" in report_by_case[case.id].checks
    ]

    for case in cases:
        observed = observed_by_case.get(case.id)
        expected_required: set[str] = set(case.expected.route.required_tools)
        expected_prohibited: set[str] = set(case.expected.route.prohibited_tools)
        required_total += len(expected_required)
        prohibited_total += len(expected_prohibited)
        if observed is None:
            continue
        steps = executed_steps(observed)
        required_hits += len(expected_required & steps)
        prohibited_clean += len(expected_prohibited - steps)

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
            total_cases,
        ),
        operational_budget_pass_rate=_check_ratio(reports, "operational_budgets"),
        missing_result_rate=_ratio(missing, total_cases),
    )


def category_evaluations(
    reports: tuple[CaseEvaluation, ...],
) -> tuple[CategoryEvaluation, ...]:
    rows: list[CategoryEvaluation] = []
    for category in dict.fromkeys(report.category for report in reports):
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


def missing_results(reports: tuple[CaseEvaluation, ...]) -> tuple[str, ...]:
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
