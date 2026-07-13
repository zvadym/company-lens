from __future__ import annotations

from pathlib import Path

import pytest

from company_lens.evals.golden import load_golden_dataset
from company_lens.evals.langfuse_sync import LangfuseSyncError, sync_dataset
from company_lens.evals.score_contract import load_score_contract
from tests.evals.fakes_langfuse import FakeLangfuse

DATASET = Path("evals/datasets/golden/core.v1.yaml")
SCORE_CONTRACT = Path("evals/score-contracts/foundation.v1.yaml")


def test_sync_rejects_wrong_project_before_mutation() -> None:
    client = FakeLangfuse(project_id="wrong-project")

    with pytest.raises(LangfuseSyncError, match="project_mismatch"):
        sync_dataset(
            client,
            load_golden_dataset(DATASET),
            load_score_contract(SCORE_CONTRACT),
            expected_project_id="project-testing",
        )

    assert client.counters.project_reads == 1
    assert client.counters.dataset_writes == 0
    assert client.counters.item_writes == 0


def test_sync_is_idempotent_and_returns_verified_snapshot() -> None:
    client = FakeLangfuse()
    dataset = load_golden_dataset(DATASET)
    contract = load_score_contract(SCORE_CONTRACT)

    first = sync_dataset(client, dataset, contract, expected_project_id="project-testing")
    second = sync_dataset(client, dataset, contract, expected_project_id="project-testing")

    assert first.snapshot.active_item_ids == second.snapshot.active_item_ids
    assert len(first.snapshot.active_item_ids) == len(dataset.cases)
    assert set(client.datasets[dataset.name].items) == set(first.snapshot.active_item_ids)
