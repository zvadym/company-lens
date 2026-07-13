from __future__ import annotations

import argparse
import json
from pathlib import Path

from company_lens.evals.github_cli import dispatch_github_reporting_command
from company_lens.evals.github_reporting import (
    BOT_LOGIN,
    COMMENT_MARKER,
    IssueComment,
    PullRequestInfo,
    render_pr_comment,
)
from company_lens.evals.models import ReportingTarget
from company_lens.evals.orchestrator import EvaluationRequest, run_evaluation
from company_lens.evals.reporting import load_evaluation_journal
from tests.evals.fakes_langfuse import FakeLangfuse
from tests.evals.test_evaluation_orchestrator import PassingAgent, _agent_provider, _settings


class FakeGitHubApi:
    def __init__(self, *, comments: tuple[IssueComment, ...] = ()) -> None:
        self.comments = comments
        self.created_body: str | None = None
        self.updated_body: str | None = None

    def get_pull_request(self, repository: str, pr_number: int) -> PullRequestInfo:
        return PullRequestInfo(head_sha="abcdef1")

    def list_comments(self, repository: str, pr_number: int) -> tuple[IssueComment, ...]:
        return self.comments

    def create_comment(self, repository: str, pr_number: int, body: str) -> None:
        self.created_body = body

    def update_comment(self, repository: str, comment_id: int, body: str) -> None:
        self.updated_body = body


def test_reporting_creates_canonical_comment_and_only_terminalizes_journal(
    tmp_path: Path,
    capsys,
) -> None:
    execution_path, journal_path = _artifacts(tmp_path)
    original_execution = execution_path.read_bytes()
    api = FakeGitHubApi()

    exit_code = dispatch_github_reporting_command(
        _args(execution_path, journal_path),
        api_provider=lambda: api,
    )

    assert exit_code == 0
    assert json.loads(capsys.readouterr().out)["comment_action"] == "created"
    assert api.created_body is not None
    assert COMMENT_MARKER in api.created_body
    assert "https://langfuse.test/run/run-1" in api.created_body
    assert execution_path.read_bytes() == original_execution
    journal = load_evaluation_journal(journal_path)
    assert journal.phase == "terminal"
    assert journal.reporting_status == "succeeded"


def test_duplicate_canonical_comments_fail_reporting_without_changing_execution(
    tmp_path: Path,
    capsys,
) -> None:
    execution_path, journal_path = _artifacts(tmp_path)
    original_execution = execution_path.read_bytes()
    comments = (
        IssueComment(id=1, author=BOT_LOGIN, body=COMMENT_MARKER),
        IssueComment(id=2, author=BOT_LOGIN, body=COMMENT_MARKER),
    )

    exit_code = dispatch_github_reporting_command(
        _args(execution_path, journal_path),
        api_provider=lambda: FakeGitHubApi(comments=comments),
    )

    assert exit_code == 2
    assert json.loads(capsys.readouterr().err)["error"]["code"] == ("duplicate_evaluation_comments")
    assert execution_path.read_bytes() == original_execution
    journal = load_evaluation_journal(journal_path)
    assert journal.reporting_status == "failed"
    assert journal.reporting_failure_codes == ("duplicate_evaluation_comments",)


def test_preflight_failure_comment_marks_missing_langfuse_run_unavailable(tmp_path: Path) -> None:
    client = FakeLangfuse(project_id="wrong-project")
    outcome = run_evaluation(
        EvaluationRequest(
            dataset_paths=(Path("evals/datasets/golden/core.v1.yaml"),),
            gate_path=Path("evals/gates/eval-fast.v1.yaml"),
            score_contract_path=Path("evals/score-contracts/foundation.v1.yaml"),
            output_dir=tmp_path,
            max_cases=1,
            commit_sha="abcdef1",
            reporting_target=ReportingTarget(repository="owner/repo", pr_number=7),
        ),
        settings=_settings(),
        client=client,
        agent_provider=_agent_provider(PassingAgent(client)),
    )

    body = render_pr_comment(outcome.execution, artifact_url="https://github.test/artifacts/1")

    assert outcome.execution.gate_status == "not_evaluated"
    assert "unavailable" in body
    assert "Infrastructure prevented a trustworthy quality verdict" in body


def _artifacts(tmp_path: Path) -> tuple[Path, Path]:
    client = FakeLangfuse()
    request = EvaluationRequest(
        dataset_paths=(Path("evals/datasets/golden/core.v1.yaml"),),
        gate_path=Path("evals/gates/eval-fast.v1.yaml"),
        score_contract_path=Path("evals/score-contracts/foundation.v1.yaml"),
        output_dir=tmp_path,
        max_cases=1,
        commit_sha="abcdef1",
        reporting_target=ReportingTarget(repository="owner/repo", pr_number=7),
    )
    outcome = run_evaluation(
        request,
        settings=_settings(),
        client=client,
        agent_provider=_agent_provider(PassingAgent(client)),
    )
    assert outcome.journal.phase == "reporting"
    return tmp_path / "evaluation-execution.json", tmp_path / "evaluation-journal.json"


def _args(execution: Path, journal: Path) -> argparse.Namespace:
    return argparse.Namespace(
        command="report-evaluation-pr",
        execution=execution,
        journal=journal,
        repository="owner/repo",
        pr_number=7,
        expected_head_sha="abcdef1",
        artifact_url="https://github.test/artifacts/1",
    )
