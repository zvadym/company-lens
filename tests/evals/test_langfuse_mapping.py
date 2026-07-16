from __future__ import annotations

from pathlib import Path

from company_lens.evals.golden import load_golden_dataset
from company_lens.evals.langfuse_mapping import item_uuid, map_golden_case, score_uuid


def test_mapping_uses_stable_project_unique_ids_and_hashes() -> None:
    dataset = load_golden_dataset(Path("evals/datasets/golden/core.v1.yaml"))
    case = dataset.cases[0]

    mapped = map_golden_case(dataset, case)

    assert mapped.id == item_uuid(dataset.name, case.id)
    assert mapped.metadata["dataset_version"] == 1
    assert mapped.metadata["case_id"] == case.id
    assert mapped.metadata["content_hash"] == mapped.content_hash
    assert len(mapped.content_hash) == 64
    assert score_uuid("run-1", "item", "case_pass", case.id) == score_uuid(
        "run-1", "item", "case_pass", case.id
    )
