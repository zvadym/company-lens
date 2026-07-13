"""Framework-neutral evaluation dataset models, validators, and deterministic scorers."""

# Re-export only the stable dataset surface so future adapters do not depend on module internals.
from company_lens.evals.agent_runner import (
    run_golden_agent_dataset,
    run_golden_agent_observations,
)
from company_lens.evals.deterministic import (
    DeterministicEvaluationReport,
    ObservedGoldenResults,
    evaluate_dataset,
    evaluate_golden_results,
)
from company_lens.evals.golden import GoldenDataset, GoldenDatasetCase, load_golden_dataset
from company_lens.evals.models import EvaluationExecution, EvaluationRecoveryJournal
from company_lens.evals.orchestrator import (
    EvaluationOutcome,
    EvaluationRequest,
    run_evaluation,
)
from company_lens.evals.replay import replay_evaluation

__all__ = [
    "DeterministicEvaluationReport",
    "EvaluationExecution",
    "EvaluationOutcome",
    "EvaluationRecoveryJournal",
    "EvaluationRequest",
    "GoldenDataset",
    "GoldenDatasetCase",
    "ObservedGoldenResults",
    "evaluate_dataset",
    "evaluate_golden_results",
    "load_golden_dataset",
    "replay_evaluation",
    "run_evaluation",
    "run_golden_agent_dataset",
    "run_golden_agent_observations",
]
