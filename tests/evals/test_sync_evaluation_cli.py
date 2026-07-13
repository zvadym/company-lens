from __future__ import annotations

import argparse
import json
from pathlib import Path

from company_lens.config import Settings
from company_lens.evals.cli import dispatch_evaluation_command, register_evaluation_commands
from tests.evals.fakes_langfuse import FakeLangfuse


def test_sync_dry_run_never_resolves_or_mutates_remote_project(capsys) -> None:
    client = FakeLangfuse()
    exit_code = dispatch_evaluation_command(
        _parse("sync-evaluation-datasets", "--dry-run"),
        settings_provider=_settings,
        client_provider=lambda: client,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["project_identity"] == "not_checked"
    assert client.counters.project_reads == 0
    assert client.counters.dataset_writes == 0
    assert payload["datasets"][0]["items"][0]["item_id"]


def test_sync_wrong_project_returns_two_with_zero_writes(capsys) -> None:
    client = FakeLangfuse(project_id="wrong")
    exit_code = dispatch_evaluation_command(
        _parse("sync-evaluation-datasets"),
        settings_provider=_settings,
        client_provider=lambda: client,
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == "evaluation_sync_failed"
    assert client.counters.dataset_writes == 0
    assert client.counters.item_writes == 0


def test_verified_sync_writes_requested_json_report(tmp_path: Path, capsys) -> None:
    client = FakeLangfuse()
    output = tmp_path / "sync.json"

    exit_code = dispatch_evaluation_command(
        _parse(
            "sync-evaluation-datasets",
            "--dataset",
            "evals/datasets/golden/core.v1.yaml",
            "--output",
            str(output),
        ),
        settings_provider=_settings,
        client_provider=lambda: client,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["status"] == "verified"
    assert len(payload["datasets"][0]["active_item_ids"]) == 14
    assert json.loads(capsys.readouterr().out) == payload


def _parse(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_evaluation_commands(subparsers)
    return parser.parse_args(argv)


def _settings() -> Settings:
    return Settings(langfuse_project_id="project-testing", _env_file=None)
