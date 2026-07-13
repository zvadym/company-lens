from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager, suppress
from pathlib import Path
from typing import Any

from company_lens.config import Settings
from company_lens.evals.models import ReportingTarget
from company_lens.evals.orchestrator import EvaluationRequest, run_evaluation
from company_lens.evals.replay import replay_evaluation
from company_lens.evals.reporting import recover_evaluation_artifacts
from company_lens.observability.langfuse_client import current_langfuse_client

EXECUTION_COMMANDS = frozenset({"run-evaluation", "recover-evaluation"})
DEFAULT_DATASETS = (
    Path("evals/datasets/golden/core.v1.yaml"),
    Path("evals/datasets/golden/follow_up.v1.yaml"),
)


def register_execution_commands(subparsers: Any) -> None:
    run_parser = subparsers.add_parser(
        "run-evaluation",
        help="Run a repository-authored evaluation as Langfuse dataset experiments.",
    )
    run_parser.add_argument("--dataset", type=Path, action="append", default=None)
    run_parser.add_argument("--gate", type=Path, default=None)
    run_parser.add_argument("--score-contract", type=Path, default=None)
    run_parser.add_argument("--manifest", type=Path, default=None)
    run_parser.add_argument("--output-dir", type=Path, default=None)
    run_parser.add_argument("--max-cases", type=int, default=None)
    run_parser.add_argument("--execution-id", type=uuid.UUID, default=None)
    run_parser.add_argument("--session-prefix", default="golden-eval")
    run_parser.add_argument("--max-concurrency", type=int, default=None)
    run_parser.add_argument("--max-tool-calls", type=int, default=None)
    run_parser.add_argument("--max-retries-per-node", type=int, default=None)
    run_parser.add_argument("--max-repair-attempts", type=int, default=None)
    run_parser.add_argument("--commit-sha", default=None)
    run_parser.add_argument("--source-ref", default=None)
    run_parser.add_argument("--workflow-run-url", default=None)
    run_parser.add_argument("--repository", default=None)
    run_parser.add_argument("--pr-number", type=int, default=None)
    run_parser.add_argument("--pretty", action="store_true")

    recover_parser = subparsers.add_parser(
        "recover-evaluation",
        help="Materialize evaluation artifacts from a recovery journal.",
    )
    recover_parser.add_argument("--journal", type=Path, required=True)
    recover_parser.add_argument("--output-dir", type=Path, default=None)
    recover_parser.add_argument("--pretty", action="store_true")


def dispatch_execution_command(
    args: argparse.Namespace,
    *,
    settings_provider: Callable[[], Settings],
    agent_provider: Callable[[Settings], AbstractContextManager[Any]],
    client_provider: Callable[[], Any] = current_langfuse_client,
) -> int | None:
    if args.command not in EXECUTION_COMMANDS:
        return None
    if args.command == "recover-evaluation":
        return _recover(args)
    return _run(
        args,
        settings_provider=settings_provider,
        agent_provider=agent_provider,
        client_provider=client_provider,
    )


def _run(
    args: argparse.Namespace,
    *,
    settings_provider: Callable[[], Settings],
    agent_provider: Callable[[Settings], AbstractContextManager[Any]],
    client_provider: Callable[[], Any],
) -> int:
    if (args.repository is None) != (args.pr_number is None):
        _print_error(
            "evaluation_reporting_target_invalid",
            "Repository and PR number must be supplied together.",
        )
        return 2
    execution_id = args.execution_id or uuid.uuid4()
    output_dir = args.output_dir or Path("artifacts/evaluations") / str(execution_id)
    target = (
        ReportingTarget(repository=args.repository, pr_number=args.pr_number)
        if args.repository is not None
        else None
    )
    previous_handlers = _install_signal_handlers()
    try:
        settings = settings_provider()
        client = client_provider()
        if args.manifest is not None:
            immutable_overrides = any(
                value is not None
                for value in (
                    args.dataset,
                    args.gate,
                    args.score_contract,
                    args.max_cases,
                    args.max_concurrency,
                    args.max_tool_calls,
                    args.max_retries_per_node,
                    args.max_repair_attempts,
                    args.commit_sha,
                    args.source_ref,
                )
            )
            if immutable_overrides:
                _print_error(
                    "evaluation_replay_override_rejected",
                    "Replay does not accept immutable evaluation overrides.",
                )
                return 2
            outcome = replay_evaluation(
                args.manifest,
                output_dir=output_dir,
                execution_id=execution_id,
                settings=settings,
                client=client,
                agent_provider=lambda: agent_provider(settings),
                session_prefix=args.session_prefix,
                workflow_run_url=args.workflow_run_url,
                workflow_actor=os.getenv("GITHUB_ACTOR"),
                reporting_target=target,
            )
        else:
            outcome = run_evaluation(
                EvaluationRequest(
                    dataset_paths=tuple(args.dataset or DEFAULT_DATASETS),
                    gate_path=args.gate or Path("evals/gates/eval-full.v1.yaml"),
                    score_contract_path=args.score_contract
                    or Path("evals/score-contracts/foundation.v1.yaml"),
                    output_dir=output_dir,
                    execution_id=execution_id,
                    max_cases=args.max_cases,
                    max_concurrency=args.max_concurrency or 1,
                    max_tool_calls=args.max_tool_calls or 10,
                    max_retries_per_node=(
                        args.max_retries_per_node if args.max_retries_per_node is not None else 2
                    ),
                    max_repair_attempts=(
                        args.max_repair_attempts if args.max_repair_attempts is not None else 1
                    ),
                    session_prefix=args.session_prefix,
                    commit_sha=args.commit_sha or os.getenv("GITHUB_SHA", "0000000"),
                    source_ref=args.source_ref or os.getenv("GITHUB_REF"),
                    workflow_run_url=args.workflow_run_url,
                    workflow_actor=os.getenv("GITHUB_ACTOR"),
                    reporting_target=target,
                ),
                settings=settings,
                client=client,
                agent_provider=lambda: agent_provider(settings),
            )
    except KeyboardInterrupt:
        journal_path = output_dir / "evaluation-journal.json"
        if journal_path.exists():
            with suppress(OSError, RuntimeError, ValueError):
                recover_evaluation_artifacts(journal_path, output_dir)
        _print_error("evaluation_interrupted", "Evaluation was interrupted and checkpointed.")
        return 2
    except (OSError, RuntimeError, ValueError):
        _print_error("evaluation_execution_failed", "Evaluation could not be completed.")
        return 2
    finally:
        _restore_signal_handlers(previous_handlers)
    print(
        json.dumps(
            {
                "execution_id": str(outcome.execution.execution_id),
                "status": outcome.execution.status,
                "gate_status": outcome.execution.gate_status,
                "output_dir": str(output_dir),
                "langfuse_runs": [run.langfuse_run_url for run in outcome.execution.runs],
            },
            indent=2 if args.pretty else None,
        )
    )
    return outcome.exit_code


def _recover(args: argparse.Namespace) -> int:
    try:
        journal, execution = recover_evaluation_artifacts(args.journal, args.output_dir)
    except (OSError, RuntimeError, ValueError):
        _print_error("evaluation_recovery_failed", "Evaluation recovery failed.")
        return 2
    print(
        json.dumps(
            {
                "execution_id": str(execution.execution_id),
                "status": execution.status,
                "gate_status": execution.gate_status,
                "journal_sequence": journal.sequence,
            },
            indent=2 if args.pretty else None,
        )
    )
    return 0


def _print_error(code: str, message: str) -> None:
    print(json.dumps({"error": {"code": code, "message": message}}), file=sys.stderr)


def _install_signal_handlers() -> dict[signal.Signals, Any]:
    previous: dict[signal.Signals, Any] = {}

    def interrupt_handler(signum: int, _: object) -> None:
        raise KeyboardInterrupt(f"evaluation interrupted by signal {signum}")

    for watched in (signal.SIGINT, signal.SIGTERM):
        previous[watched] = signal.getsignal(watched)
        signal.signal(watched, interrupt_handler)
    return previous


def _restore_signal_handlers(previous: dict[signal.Signals, Any]) -> None:
    for watched, handler in previous.items():
        signal.signal(watched, handler)
