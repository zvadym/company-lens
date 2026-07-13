from __future__ import annotations

from company_lens.evals.execution_artifacts import (
    format_execution_summary,
    materialize_execution_artifacts,
    recover_evaluation_artifacts,
)
from company_lens.evals.journal import (
    EvaluationJournalError,
    checkpoint_evaluation_journal,
    initialize_evaluation_journal,
    load_evaluation_journal,
)
from company_lens.evals.models import DeterministicEvaluationReport


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
            lines.append(f"- `{case.case_id}` (`{case.category}`): {'; '.join(case.failures)}")
    if report.gate is not None and report.gate.failures:
        lines.extend(["", "## Gate Failures", ""])
        for failure in report.gate.failures:
            lines.append(
                f"- `{failure.metric}` {failure.comparator} {failure.threshold:.3f}; "
                f"actual {failure.actual:.3f}"
            )
    return "\n".join(lines)


__all__ = [
    "EvaluationJournalError",
    "checkpoint_evaluation_journal",
    "format_execution_summary",
    "format_markdown_report",
    "initialize_evaluation_journal",
    "load_evaluation_journal",
    "materialize_execution_artifacts",
    "recover_evaluation_artifacts",
]
