"""Compatibility facade for deterministic evaluation APIs."""

from company_lens.evals.checks import (
    evaluate_dataset,
    evaluate_golden_results,
    load_observed_results,
)
from company_lens.evals.gates import (
    EvaluationGate,
    EvaluationGateFailure,
    EvaluationGateResult,
    OperationalBudget,
    RegressionGate,
    RegressionGateFailure,
    RegressionGateResult,
    evaluate_gate,
    load_evaluation_gate,
    load_regression_gate,
)
from company_lens.evals.models import (
    CaseEvaluation,
    CategoryEvaluation,
    DeterministicEvaluationReport,
    EvaluationMetrics,
    EvaluationModel,
    ObservedCaseResult,
    ObservedCompany,
    ObservedGoldenResults,
    ObservedNodeAttempt,
    ObservedNodeLatency,
    ObservedOperationalMetrics,
    ObservedTrajectoryEvent,
)
from company_lens.evals.reporting import format_markdown_report

__all__ = [
    "CaseEvaluation",
    "CategoryEvaluation",
    "DeterministicEvaluationReport",
    "EvaluationGate",
    "EvaluationGateFailure",
    "EvaluationGateResult",
    "EvaluationMetrics",
    "EvaluationModel",
    "ObservedCaseResult",
    "ObservedCompany",
    "ObservedGoldenResults",
    "ObservedNodeAttempt",
    "ObservedNodeLatency",
    "ObservedOperationalMetrics",
    "ObservedTrajectoryEvent",
    "OperationalBudget",
    "RegressionGate",
    "RegressionGateFailure",
    "RegressionGateResult",
    "evaluate_dataset",
    "evaluate_gate",
    "evaluate_golden_results",
    "format_markdown_report",
    "load_evaluation_gate",
    "load_observed_results",
    "load_regression_gate",
]
