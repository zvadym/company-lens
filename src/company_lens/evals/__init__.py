"""Framework-neutral evaluation dataset models, validators, and deterministic scorers."""

# Re-export only the stable dataset surface so future adapters do not depend on module internals.
from company_lens.evals.agent_runner import run_golden_agent_dataset
from company_lens.evals.deterministic import (
    DeterministicEvaluationReport,
    ObservedGoldenResults,
    evaluate_dataset,
    evaluate_golden_results,
)
from company_lens.evals.golden import GoldenDataset, GoldenDatasetCase, load_golden_dataset

__all__ = [
    "DeterministicEvaluationReport",
    "GoldenDataset",
    "GoldenDatasetCase",
    "ObservedGoldenResults",
    "evaluate_dataset",
    "evaluate_golden_results",
    "load_golden_dataset",
    "run_golden_agent_dataset",
]
