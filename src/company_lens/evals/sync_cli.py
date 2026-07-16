from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from company_lens.config import Settings
from company_lens.evals.golden import load_golden_dataset
from company_lens.evals.langfuse_mapping import map_golden_case
from company_lens.evals.langfuse_sync import sync_dataset
from company_lens.evals.score_contract import load_score_contract
from company_lens.observability.langfuse_client import current_langfuse_client

SYNC_COMMAND = "sync-evaluation-datasets"
DEFAULT_DATASETS = (
    Path("evals/datasets/golden/core.v1.yaml"),
    Path("evals/datasets/golden/follow_up.v1.yaml"),
)


def register_sync_command(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        SYNC_COMMAND,
        help="Synchronize repository evaluation datasets and score configs to Langfuse.",
    )
    parser.add_argument("--dataset", type=Path, action="append", default=None)
    parser.add_argument(
        "--score-contract",
        type=Path,
        default=Path("evals/score-contracts/foundation.v1.yaml"),
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--pretty", action="store_true")


def dispatch_sync_command(
    args: argparse.Namespace,
    *,
    settings_provider: Callable[[], Settings],
    client_provider: Callable[[], Any] = current_langfuse_client,
) -> int | None:
    if args.command != SYNC_COMMAND:
        return None
    try:
        settings = settings_provider()
        if not settings.langfuse_project_id:
            raise ValueError("expected project ID is required")
        datasets = tuple(load_golden_dataset(path) for path in (args.dataset or DEFAULT_DATASETS))
        contract = load_score_contract(args.score_contract)
        if args.dry_run:
            payload = {
                "status": "dry_run",
                "project_identity": "not_checked",
                "expected_project_id": settings.langfuse_project_id,
                "datasets": [
                    {
                        "name": dataset.name,
                        "version": dataset.version,
                        "content_hash": dataset.content_hash,
                        "items": [
                            {
                                "case_id": case.id,
                                "item_id": mapped.id,
                                "content_hash": mapped.content_hash,
                            }
                            for case in dataset.cases
                            for mapped in (map_golden_case(dataset, case),)
                        ],
                    }
                    for dataset in datasets
                ],
                "score_configs": [definition.name for definition in contract.scores],
            }
        else:
            client = client_provider()
            results = [
                sync_dataset(
                    client,
                    dataset,
                    contract,
                    expected_project_id=settings.langfuse_project_id,
                )
                for dataset in datasets
            ]
            payload = {
                "status": "verified",
                "project_identity": "verified",
                "expected_project_id": settings.langfuse_project_id,
                "datasets": [
                    {
                        "name": result.snapshot.dataset_name,
                        "dataset_id": result.snapshot.langfuse_dataset_id,
                        "version_timestamp": result.snapshot.version_timestamp.isoformat(),
                        "active_item_ids": result.snapshot.active_item_ids,
                        "stale_item_ids": result.stale_item_ids,
                    }
                    for result in results
                ],
                "score_configs": [
                    binding.model_dump(mode="json") for binding in results[0].score_configs.bindings
                ]
                if results
                else [],
            }
        rendered = json.dumps(payload, indent=2 if args.pretty else None)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except (OSError, RuntimeError, ValueError):
        print(
            json.dumps(
                {
                    "error": {
                        "code": "evaluation_sync_failed",
                        "message": "Evaluation dataset synchronization failed.",
                    }
                }
            ),
            file=sys.stderr,
        )
        return 2
