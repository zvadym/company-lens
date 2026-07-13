from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from company_lens.agent.application import (
    ResearchApplicationConfigurationError,
    open_persistent_research_agent,
)
from company_lens.agent.persistence import ResearchSessionError
from company_lens.agent.schemas import ExecutionPolicy
from company_lens.config import get_settings
from company_lens.evals.agent_runner import run_golden_agent_dataset
from company_lens.evals.checks import evaluate_golden_results
from company_lens.evals.evaluation_cli import (
    dispatch_execution_command,
    register_execution_commands,
)
from company_lens.evals.gates import load_evaluation_gate
from company_lens.evals.github_cli import (
    dispatch_github_reporting_command,
    register_github_reporting_command,
)
from company_lens.evals.golden import (
    golden_dataset_summary,
    load_golden_dataset,
    validate_golden_dataset,
)
from company_lens.evals.reporting import format_markdown_report
from company_lens.evals.sync_cli import dispatch_sync_command, register_sync_command

EVALUATION_COMMANDS = frozenset(
    {"validate-golden-dataset", "evaluate-golden-results", "run-golden-agent"}
)


def register_evaluation_commands(subparsers: Any) -> None:
    register_execution_commands(subparsers)
    register_sync_command(subparsers)
    register_github_reporting_command(subparsers)
    golden_parser = subparsers.add_parser(
        "validate-golden-dataset",
        help="Validate a framework-neutral golden evaluation dataset.",
    )
    golden_parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/golden/follow_up.v1.yaml"),
        help="Path to golden dataset YAML.",
    )
    golden_parser.add_argument("--pretty", action="store_true", help="Indent JSON output.")

    eval_parser = subparsers.add_parser(
        "evaluate-golden-results",
        help="Score observed golden-case results with deterministic checks.",
    )
    eval_parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/golden/follow_up.v1.yaml"),
        help="Path to golden dataset YAML.",
    )
    eval_parser.add_argument(
        "--results", type=Path, required=True, help="Path to observed golden results JSON."
    )
    eval_parser.add_argument(
        "--gate", type=Path, default=None, help="Optional versioned evaluation gate YAML."
    )
    eval_parser.add_argument(
        "--markdown-output",
        type=Path,
        default=None,
        help="Optional path for a human-readable Markdown report.",
    )
    eval_parser.add_argument("--pretty", action="store_true", help="Indent JSON output.")

    run_parser = subparsers.add_parser(
        "run-golden-agent",
        help="Run the live research agent against golden cases and write observed results JSON.",
    )
    run_parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("evals/datasets/golden/core.v1.yaml"),
        help="Path to golden dataset YAML.",
    )
    run_parser.add_argument(
        "--output",
        type=Path,
        default=Path("observed-results.json"),
        help="Path for observed results JSON.",
    )
    run_parser.add_argument(
        "--case-id",
        action="append",
        dest="case_ids",
        default=None,
        help="Specific golden case id to run. Can be repeated.",
    )
    run_parser.add_argument("--max-cases", type=int, default=None)
    run_parser.add_argument("--session-prefix", default="golden-eval")
    run_parser.add_argument("--max-tool-calls", type=int, default=10)
    run_parser.add_argument("--max-retries-per-node", type=int, default=2)
    run_parser.add_argument("--max-repair-attempts", type=int, default=1)
    run_parser.add_argument("--pretty", action="store_true", help="Indent JSON output.")


def dispatch_evaluation_command(
    args: argparse.Namespace,
    *,
    settings_provider: Callable[[], Any] = get_settings,
    agent_provider: Callable[[Any], AbstractContextManager[Any]] = open_persistent_research_agent,
    client_provider: Callable[[], Any] | None = None,
) -> int | None:
    execution_result = dispatch_execution_command(
        args,
        settings_provider=settings_provider,
        agent_provider=agent_provider,
        **({"client_provider": client_provider} if client_provider is not None else {}),
    )
    if execution_result is not None:
        return execution_result
    sync_result = dispatch_sync_command(
        args,
        settings_provider=settings_provider,
        **({"client_provider": client_provider} if client_provider is not None else {}),
    )
    if sync_result is not None:
        return sync_result
    reporting_result = dispatch_github_reporting_command(args)
    if reporting_result is not None:
        return reporting_result
    if args.command not in EVALUATION_COMMANDS:
        return None
    if args.command == "validate-golden-dataset":
        return _run_validate_golden_dataset(args)
    if args.command == "evaluate-golden-results":
        return _run_evaluate_golden_results(args)
    return _run_golden_agent(
        args,
        settings_provider=settings_provider,
        agent_provider=agent_provider,
    )


def _run_validate_golden_dataset(args: argparse.Namespace) -> int:
    try:
        dataset = validate_golden_dataset(args.dataset)
    except (OSError, ValueError) as exc:
        print(f"Golden dataset validation failed: {exc}")
        return 1
    print(json.dumps(golden_dataset_summary(dataset), indent=2 if args.pretty else None))
    return 0


def _run_evaluate_golden_results(args: argparse.Namespace) -> int:
    try:
        gate = load_evaluation_gate(args.gate) if args.gate is not None else None
        report = evaluate_golden_results(args.dataset, args.results, gate=gate)
        if args.markdown_output is not None:
            args.markdown_output.write_text(format_markdown_report(report) + "\n", encoding="utf-8")
    except (OSError, ValueError) as exc:
        print(f"Golden result evaluation failed: {exc}")
        return 1
    print(report.model_dump_json(indent=2 if args.pretty else None))
    return 0 if report.passed else 1


def _run_golden_agent(
    args: argparse.Namespace,
    *,
    settings_provider: Callable[[], Any],
    agent_provider: Callable[[Any], AbstractContextManager[Any]],
) -> int:
    try:
        dataset = load_golden_dataset(args.dataset)
        policy = ExecutionPolicy(
            max_tool_calls=args.max_tool_calls,
            max_retries_per_node=args.max_retries_per_node,
            max_repair_attempts=args.max_repair_attempts,
        )
        with agent_provider(settings_provider()) as agent:
            observed = run_golden_agent_dataset(
                dataset,
                agent,
                policy=policy,
                max_cases=args.max_cases,
                case_ids=tuple(args.case_ids or ()),
                session_prefix=args.session_prefix,
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            observed.model_dump_json(indent=2 if args.pretty else None) + "\n",
            encoding="utf-8",
        )
    except (
        OSError,
        ValueError,
        ResearchApplicationConfigurationError,
        ResearchSessionError,
    ) as exc:
        print(f"Golden agent run failed: {exc}")
        return 1
    print(
        json.dumps(
            {
                "dataset": observed.dataset_name,
                "version": observed.dataset_version,
                "results": len(observed.results),
                "output": str(args.output),
            },
            indent=2 if args.pretty else None,
        )
    )
    return 0
