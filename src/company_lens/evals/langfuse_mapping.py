from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Any

from company_lens.evals.golden import GoldenDataset, GoldenDatasetCase


@dataclass(frozen=True)
class MappedDatasetItem:
    id: str
    input: dict[str, Any]
    expected_output: dict[str, Any]
    metadata: dict[str, Any]
    content_hash: str


def item_uuid(dataset_name: str, case_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"company-lens:{dataset_name}:{case_id}"))


def score_uuid(
    dataset_run_id: str,
    scope: str,
    score_name: str,
    case_id: str | None = None,
) -> str:
    suffix = f":{case_id}" if case_id else ""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{dataset_run_id}:{scope}:{score_name}{suffix}"))


def canonical_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def map_golden_case(dataset: GoldenDataset, case: GoldenDatasetCase) -> MappedDatasetItem:
    if dataset.source_path is None:
        raise ValueError("Golden dataset source path is required for Langfuse mapping.")
    item_input = {
        "conversation": [turn.model_dump(mode="json") for turn in case.conversation],
    }
    expected_output = {
        "behavior": case.expected.model_dump(mode="json", by_alias=True),
        "citation": {
            "mode": case.citation_mode,
            "scenario": case.citation_scenario,
        },
        "notes": case.notes,
    }
    metadata: dict[str, Any] = {
        "schema_version": 1,
        "source": "repository",
        "source_path": dataset.source_path.as_posix(),
        "dataset_name": dataset.name,
        "dataset_version": dataset.version,
        "case_id": case.id,
        "category": case.category,
    }
    content_hash = canonical_hash(
        {
            "input": item_input,
            "expected_output": expected_output,
            "metadata": metadata,
        }
    )
    metadata["content_hash"] = content_hash
    return MappedDatasetItem(
        id=item_uuid(dataset.name, case.id),
        input=item_input,
        expected_output=expected_output,
        metadata=metadata,
        content_hash=content_hash,
    )
