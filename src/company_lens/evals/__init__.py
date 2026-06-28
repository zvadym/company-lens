"""Framework-neutral evaluation dataset models and validators."""

# Re-export only the stable dataset surface so future adapters do not depend on module internals.
from company_lens.evals.golden import GoldenDataset, GoldenDatasetCase, load_golden_dataset

__all__ = ["GoldenDataset", "GoldenDatasetCase", "load_golden_dataset"]
