from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from company_lens.evals.golden import GoldenDataset
from company_lens.evals.langfuse_mapping import MappedDatasetItem, map_golden_case
from company_lens.evals.langfuse_scores import ReconciledScoreConfigs, reconcile_score_configs
from company_lens.evals.manifest import DatasetSnapshot
from company_lens.evals.score_contract import ScoreContract
from company_lens.observability.langfuse_client import (
    LangfuseClientUnavailable,
    LangfuseProjectMismatch,
    verify_langfuse_project,
)


class LangfuseSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class DatasetSyncResult:
    snapshot: DatasetSnapshot
    score_configs: ReconciledScoreConfigs
    stale_item_ids: tuple[str, ...]


def sync_dataset(
    client: Any,
    dataset: GoldenDataset,
    score_contract: ScoreContract,
    *,
    expected_project_id: str | None,
) -> DatasetSyncResult:
    try:
        project = verify_langfuse_project(client, expected_project_id)
    except LangfuseProjectMismatch as exc:
        raise LangfuseSyncError("project_mismatch") from exc
    except LangfuseClientUnavailable as exc:
        raise LangfuseSyncError("project_unavailable") from exc

    mapped = tuple(map_golden_case(dataset, case) for case in dataset.cases)
    expected = {item.id: item for item in mapped}
    existing = _existing_items(client, dataset.name)
    stale_ids = tuple(sorted(set(existing) - set(expected)))
    client.create_dataset(
        name=dataset.name,
        description=dataset.description,
        metadata={
            "source": "repository",
            "source_path": _source_path(dataset),
            "dataset_version": dataset.version,
            "content_hash": dataset.content_hash,
        },
    )
    timestamps: list[datetime] = []
    for item in mapped:
        created = _upsert_item(client, dataset.name, item, status="ACTIVE")
        timestamps.append(_timestamp(created))
    for item_id in stale_ids:
        stale = existing[item_id]
        created = client.create_dataset_item(
            id=item_id,
            dataset_name=dataset.name,
            input=_value(stale, "input") or {},
            expected_output=_value(stale, "expected_output") or {},
            metadata=_value(stale, "metadata") or {},
            status="ARCHIVED",
        )
        timestamps.append(_timestamp(created))

    score_configs = reconcile_score_configs(client, score_contract)
    version_timestamp = max(timestamps, default=datetime.now(UTC))
    pinned = client.get_dataset(dataset.name, version=version_timestamp)
    active_items = {
        str(_value(item, "id")): item
        for item in _items(pinned)
        if str(_value(item, "status") or "ACTIVE").upper() == "ACTIVE"
    }
    _verify_items(active_items, expected)
    snapshot = DatasetSnapshot(
        dataset_name=dataset.name,
        repository_version=dataset.version,
        source_path=_source_path(dataset),
        repository_hash=dataset.content_hash or "",
        langfuse_project_id=project.id,
        langfuse_dataset_id=str(_value(pinned, "id")),
        version_timestamp=version_timestamp,
        active_item_ids=tuple(sorted(active_items)),
        active_item_hashes={
            item_id: str((_value(item, "metadata") or {}).get("content_hash"))
            for item_id, item in sorted(active_items.items())
        },
        stale_item_ids=stale_ids,
        selected_case_ids=tuple(case.id for case in dataset.cases),
    )
    return DatasetSyncResult(snapshot, score_configs, stale_ids)


def load_recorded_snapshot(
    client: Any,
    snapshot: DatasetSnapshot,
    *,
    expected_project_id: str | None,
) -> Any:
    try:
        project = verify_langfuse_project(client, expected_project_id)
    except (LangfuseClientUnavailable, LangfuseProjectMismatch) as exc:
        raise LangfuseSyncError("project_unavailable_or_mismatched") from exc
    if project.id != snapshot.langfuse_project_id:
        raise LangfuseSyncError("snapshot_project_mismatch")
    pinned = client.get_dataset(snapshot.dataset_name, version=snapshot.version_timestamp)
    items = {
        str(_value(item, "id")): item
        for item in _items(pinned)
        if str(_value(item, "status") or "ACTIVE").upper() == "ACTIVE"
    }
    if set(items) != set(snapshot.active_item_ids):
        raise LangfuseSyncError("snapshot_item_mismatch")
    hashes = {
        item_id: str((_value(item, "metadata") or {}).get("content_hash"))
        for item_id, item in items.items()
    }
    if hashes != snapshot.active_item_hashes:
        raise LangfuseSyncError("snapshot_hash_mismatch")
    return pinned


def _existing_items(client: Any, dataset_name: str) -> dict[str, Any]:
    try:
        remote = client.get_dataset(dataset_name)
    except (KeyError, LookupError):
        return {}
    return {str(_value(item, "id")): item for item in _items(remote)}


def _upsert_item(client: Any, dataset_name: str, item: MappedDatasetItem, *, status: str) -> Any:
    return client.create_dataset_item(
        id=item.id,
        dataset_name=dataset_name,
        input=item.input,
        expected_output=item.expected_output,
        metadata=item.metadata,
        status=status,
    )


def _verify_items(remote: dict[str, Any], expected: dict[str, MappedDatasetItem]) -> None:
    if set(remote) != set(expected):
        raise LangfuseSyncError("active_item_id_mismatch")
    for item_id, mapped in expected.items():
        metadata = _value(remote[item_id], "metadata") or {}
        if metadata.get("content_hash") != mapped.content_hash:
            raise LangfuseSyncError(f"content_hash_mismatch:{item_id}")


def _items(dataset: Any) -> list[Any]:
    return list(_value(dataset, "items") or ())


def _timestamp(value: Any) -> datetime:
    timestamp = _value(value, "updated_at") or _value(value, "updatedAt")
    return timestamp if isinstance(timestamp, datetime) else datetime.now(UTC)


def _source_path(dataset: GoldenDataset) -> str:
    if dataset.source_path is None:
        raise LangfuseSyncError("missing_source_path")
    return dataset.source_path.as_posix()


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
