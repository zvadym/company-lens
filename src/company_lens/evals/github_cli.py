from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from company_lens.evals.github_reporting import (
    GitHubReportingError,
    HttpGitHubReportingApi,
    report_evaluation_to_pr,
)
from company_lens.evals.journal import (
    checkpoint_evaluation_journal,
    load_evaluation_journal,
)
from company_lens.evals.models import EvaluationExecution

REPORT_COMMAND = "report-evaluation-pr"


def register_github_reporting_command(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        REPORT_COMMAND,
        help="Create or update the canonical evaluation summary on a pull request.",
    )
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--pr-number", type=int, required=True)
    parser.add_argument("--expected-head-sha", required=True)
    parser.add_argument("--artifact-url", required=True)


def dispatch_github_reporting_command(
    args: argparse.Namespace,
    *,
    api_provider: Callable[[], Any] | None = None,
) -> int | None:
    if args.command != REPORT_COMMAND:
        return None
    execution_bytes = b""
    try:
        execution_bytes = args.execution.read_bytes()
        execution = EvaluationExecution.model_validate_json(execution_bytes)
        journal = load_evaluation_journal(args.journal)
        api = api_provider() if api_provider is not None else _api_from_environment()
        action = report_evaluation_to_pr(
            api,
            execution,
            journal,
            repository=args.repository,
            pr_number=args.pr_number,
            expected_head_sha=args.expected_head_sha,
            artifact_url=args.artifact_url,
        )
        updated = checkpoint_evaluation_journal(
            args.journal,
            journal,
            phase="terminal",
            reporting_status="succeeded",
        )
        if args.execution.read_bytes() != execution_bytes:
            raise GitHubReportingError("execution_artifact_changed")
        print(
            json.dumps(
                {
                    "execution_id": str(execution.execution_id),
                    "reporting_status": updated.reporting_status,
                    "comment_action": action,
                }
            )
        )
        return 0
    except (GitHubReportingError, OSError, RuntimeError, ValueError) as exc:
        code = exc.code if isinstance(exc, GitHubReportingError) else "github_reporting_failed"
        try:
            journal = load_evaluation_journal(args.journal)
            if journal.phase == "reporting" and journal.reporting_status == "pending":
                checkpoint_evaluation_journal(
                    args.journal,
                    journal,
                    phase="terminal",
                    reporting_status="failed",
                    reporting_failure_codes=(code,),
                )
        except (OSError, RuntimeError, ValueError):
            pass
        if (
            execution_bytes
            and args.execution.exists()
            and args.execution.read_bytes() != execution_bytes
        ):
            code = "execution_artifact_changed"
        print(
            json.dumps(
                {
                    "error": {
                        "code": code,
                        "message": "Evaluation PR reporting failed.",
                    }
                }
            ),
            file=sys.stderr,
        )
        return 2


def _api_from_environment() -> HttpGitHubReportingApi:
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        raise GitHubReportingError("github_token_unavailable")
    return HttpGitHubReportingApi(token)
