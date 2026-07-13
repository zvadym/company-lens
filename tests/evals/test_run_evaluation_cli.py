from __future__ import annotations

import argparse
import json
import signal
from pathlib import Path

import pytest

from company_lens.config import Settings
from company_lens.evals.cli import dispatch_evaluation_command, register_evaluation_commands
from company_lens.evals.evaluation_cli import (
    _install_signal_handlers,
    _restore_signal_handlers,
)
from tests.evals.fakes_langfuse import FakeLangfuse
from tests.evals.test_evaluation_orchestrator import PassingAgent, _agent_provider


def test_run_evaluation_cli_returns_trusted_exit_and_artifact_paths(
    tmp_path: Path,
    capsys,
) -> None:
    client = FakeLangfuse()
    agent = PassingAgent(client)
    args = _parse(
        "run-evaluation",
        "--dataset",
        "evals/datasets/golden/core.v1.yaml",
        "--gate",
        "evals/gates/eval-fast.v1.yaml",
        "--output-dir",
        str(tmp_path),
        "--max-cases",
        "1",
        "--commit-sha",
        "abcdef1",
    )

    exit_code = dispatch_evaluation_command(
        args,
        settings_provider=_settings,
        agent_provider=lambda _: _agent_provider(agent)(),
        client_provider=lambda: client,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["gate_status"] == "passed"
    assert payload["langfuse_runs"] == ["https://langfuse.test/run/run-1"]
    assert (tmp_path / "evaluation-journal.json").exists()


def test_replay_cli_rejects_immutable_overrides_without_mutation(
    tmp_path: Path,
    capsys,
) -> None:
    client = FakeLangfuse()
    args = _parse(
        "run-evaluation",
        "--manifest",
        str(tmp_path / "source.json"),
        "--dataset",
        "evals/datasets/golden/core.v1.yaml",
    )

    exit_code = dispatch_evaluation_command(
        args,
        settings_provider=_settings,
        agent_provider=lambda _: _agent_provider(PassingAgent(client))(),
        client_provider=lambda: client,
    )

    error = json.loads(capsys.readouterr().err)
    assert exit_code == 2
    assert error["error"]["code"] == "evaluation_replay_override_rejected"
    assert client.counters.project_reads == 0


def test_evaluation_signal_handlers_convert_sigterm_to_checkpointable_interrupt() -> None:
    previous = _install_signal_handlers()
    try:
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        with pytest.raises(KeyboardInterrupt):
            handler(signal.SIGTERM, None)
    finally:
        _restore_signal_handlers(previous)


def _parse(*argv: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_evaluation_commands(subparsers)
    return parser.parse_args(argv)


def _settings() -> Settings:
    return Settings(langfuse_project_id="project-testing", _env_file=None)
