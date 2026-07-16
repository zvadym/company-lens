from __future__ import annotations

import json
from pathlib import Path

from company_lens.evals.case_checks import evaluate_case
from company_lens.evals.gates import EvaluationGate, evaluate_gate
from company_lens.evals.golden import GoldenDataset, load_golden_dataset
from company_lens.evals.metrics import category_evaluations, evaluation_metrics, missing_results
from company_lens.evals.models import (
    DeterministicEvaluationReport,
    ObservedGoldenResults,
)


def load_observed_results(path: Path) -> ObservedGoldenResults:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Observed results must be a JSON object.")
    return ObservedGoldenResults.model_validate(payload)


def evaluate_golden_results(
    dataset_path: Path,
    results_path: Path,
    *,
    gate: EvaluationGate | None = None,
) -> DeterministicEvaluationReport:
    return evaluate_dataset(
        load_golden_dataset(dataset_path),
        load_observed_results(results_path),
        gate=gate,
    )


def evaluate_dataset(
    dataset: GoldenDataset,
    observed: ObservedGoldenResults,
    *,
    gate: EvaluationGate | None = None,
) -> DeterministicEvaluationReport:
    _validate_dataset_identity(dataset, observed)
    observed_by_case = {result.case_id: result for result in observed.results}
    expected_case_ids = {case.id for case in dataset.cases}
    case_reports = tuple(
        evaluate_case(case, observed_by_case.get(case.id), gate=gate) for case in dataset.cases
    )
    metrics = evaluation_metrics(dataset.cases, case_reports, observed_by_case)
    passed_cases = sum(1 for report in case_reports if report.passed)
    missing = missing_results(case_reports)
    report = DeterministicEvaluationReport(
        dataset_name=dataset.name,
        dataset_version=dataset.version,
        passed=passed_cases == len(dataset.cases),
        total_cases=len(dataset.cases),
        evaluated_cases=len(dataset.cases) - len(missing),
        passed_cases=passed_cases,
        failed_cases=len(dataset.cases) - passed_cases,
        missing_results=missing,
        extra_results=tuple(sorted(set(observed_by_case) - expected_case_ids)),
        metrics=metrics,
        categories=category_evaluations(case_reports),
        cases=case_reports,
    )
    if gate is None:
        return report
    gate_result = evaluate_gate(report.metrics, gate)
    return report.model_copy(
        update={"passed": report.passed and gate_result.passed, "gate": gate_result}
    )


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
