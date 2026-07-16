from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from typing import Any

from company_lens.evals.manifest import DatasetSnapshot


class DatasetRunItemReconciliationError(RuntimeError):
    pass


def reconcile_dataset_run_items(
    client: Any,
    item_results: Iterable[Any],
    *,
    run_name: str,
    run_id: str,
    snapshot: DatasetSnapshot,
    execution_id: str,
    manifest_fingerprint: str,
    max_attempts: int = 3,
    retry_delay_seconds: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    metadata = {
        "evaluation_execution_id": execution_id,
        "manifest_fingerprint": manifest_fingerprint,
        "dataset_version_timestamp": snapshot.version_timestamp.isoformat(),
    }
    for item_result in item_results:
        item_id = _result_item_id(item_result)
        trace_id = str(_value(item_result, "trace_id") or "")
        if not item_id or not trace_id:
            raise DatasetRunItemReconciliationError("dataset_run_item_identity_missing")
        linked_run_id = _create_dataset_run_item(
            client,
            run_name=run_name,
            item_id=item_id,
            trace_id=trace_id,
            snapshot=snapshot,
            metadata=metadata,
            max_attempts=max_attempts,
            retry_delay_seconds=retry_delay_seconds,
            sleep=sleep,
        )
        if linked_run_id != run_id:
            raise DatasetRunItemReconciliationError("dataset_run_item_run_mismatch")


def resolve_dataset_run_url(
    client: Any,
    supplied_url: Any,
    *,
    snapshot: DatasetSnapshot,
    run_id: str,
) -> str | None:
    if supplied_url:
        return str(supplied_url)
    base_url = str(_value(client, "_base_url") or "").rstrip("/")
    if not base_url:
        return None
    return (
        f"{base_url}/project/{snapshot.langfuse_project_id}"
        f"/datasets/{snapshot.langfuse_dataset_id}/runs/{run_id}"
    )


def _create_dataset_run_item(
    client: Any,
    *,
    run_name: str,
    item_id: str,
    trace_id: str,
    snapshot: DatasetSnapshot,
    metadata: dict[str, str],
    max_attempts: int,
    retry_delay_seconds: float,
    sleep: Callable[[float], None],
) -> str:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    for attempt in range(1, max_attempts + 1):
        try:
            linked = client.api.dataset_run_items.create(
                run_name=run_name,
                dataset_item_id=item_id,
                trace_id=trace_id,
                dataset_version=snapshot.version_timestamp,
                metadata=metadata,
            )
            return str(_value(linked, "dataset_run_id") or "")
        except Exception as exc:
            if attempt == max_attempts:
                raise DatasetRunItemReconciliationError(
                    "dataset_run_item_reconciliation_failed"
                ) from exc
            sleep(retry_delay_seconds * attempt)
    raise AssertionError("unreachable")


def _result_item_id(result: Any) -> str:
    direct = _value(result, "dataset_item_id")
    if direct:
        return str(direct)
    return str(_value(_value(result, "item"), "id") or "")


def _value(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)
