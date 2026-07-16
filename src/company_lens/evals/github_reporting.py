from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx

from company_lens.evals.models import EvaluationExecution, EvaluationRecoveryJournal

COMMENT_MARKER = "<!-- company-lens-evaluation-foundation -->"
BOT_LOGIN = "github-actions[bot]"


class GitHubReportingError(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class PullRequestInfo:
    head_sha: str


@dataclass(frozen=True)
class IssueComment:
    id: int
    author: str
    body: str


class GitHubReportingApi(Protocol):
    def get_pull_request(self, repository: str, pr_number: int) -> PullRequestInfo: ...

    def list_comments(self, repository: str, pr_number: int) -> tuple[IssueComment, ...]: ...

    def create_comment(self, repository: str, pr_number: int, body: str) -> None: ...

    def update_comment(self, repository: str, comment_id: int, body: str) -> None: ...


class HttpGitHubReportingApi:
    def __init__(self, token: str, *, base_url: str = "https://api.github.com") -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=15,
        )

    def get_pull_request(self, repository: str, pr_number: int) -> PullRequestInfo:
        payload = self._get(f"/repos/{repository}/pulls/{pr_number}")
        return PullRequestInfo(head_sha=str(payload["head"]["sha"]))

    def list_comments(self, repository: str, pr_number: int) -> tuple[IssueComment, ...]:
        response = self._client.get(f"/repos/{repository}/issues/{pr_number}/comments")
        self._raise(response)
        return tuple(
            IssueComment(
                id=int(item["id"]),
                author=str(item.get("user", {}).get("login", "")),
                body=str(item.get("body", "")),
            )
            for item in response.json()
        )

    def create_comment(self, repository: str, pr_number: int, body: str) -> None:
        response = self._client.post(
            f"/repos/{repository}/issues/{pr_number}/comments", json={"body": body}
        )
        self._raise(response)

    def update_comment(self, repository: str, comment_id: int, body: str) -> None:
        response = self._client.patch(
            f"/repos/{repository}/issues/comments/{comment_id}", json={"body": body}
        )
        self._raise(response)

    def _get(self, path: str) -> dict[str, Any]:
        response = self._client.get(path)
        self._raise(response)
        payload = response.json()
        if not isinstance(payload, dict):
            raise GitHubReportingError("github_response_invalid")
        return payload

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.is_success:
            return
        code = (
            "github_permission_denied"
            if response.status_code in {401, 403}
            else "github_api_failed"
        )
        raise GitHubReportingError(code)


def report_evaluation_to_pr(
    api: GitHubReportingApi,
    execution: EvaluationExecution,
    journal: EvaluationRecoveryJournal,
    *,
    repository: str,
    pr_number: int,
    expected_head_sha: str,
    artifact_url: str,
) -> LiteralAction:
    target = journal.reporting_target
    if (
        journal.execution_id != execution.execution_id
        or journal.phase != "reporting"
        or journal.reporting_status != "pending"
        or target is None
        or target.repository != repository
        or target.pr_number != pr_number
    ):
        raise GitHubReportingError("reporting_artifact_mismatch")
    pull = api.get_pull_request(repository, pr_number)
    if pull.head_sha != expected_head_sha or execution.manifest.commit_sha != expected_head_sha:
        raise GitHubReportingError("pull_request_head_mismatch")
    comments = tuple(
        comment
        for comment in api.list_comments(repository, pr_number)
        if comment.author == BOT_LOGIN and COMMENT_MARKER in comment.body
    )
    if len(comments) > 1:
        raise GitHubReportingError("duplicate_evaluation_comments")
    body = render_pr_comment(execution, artifact_url=artifact_url)
    if comments:
        api.update_comment(repository, comments[0].id, body)
        return "updated"
    api.create_comment(repository, pr_number, body)
    return "created"


def render_pr_comment(execution: EvaluationExecution, *, artifact_url: str) -> str:
    lines = [
        COMMENT_MARKER,
        "## CompanyLens evaluation",
        "",
        f"- Execution: `{execution.execution_id}`",
        f"- Commit: `{execution.manifest.commit_sha}`",
        f"- Status: `{execution.status}`",
        f"- Gate: `{execution.gate_status}`",
        f"- Artifacts: [open workflow artifact]({artifact_url})",
        "",
        "| Dataset | Version | Cases | Langfuse |",
        "| --- | ---: | ---: | --- |",
    ]
    for run in execution.runs:
        link = f"[open run]({run.langfuse_run_url})" if run.langfuse_run_url else "unavailable"
        lines.append(
            f"| `{run.dataset_name}` | {run.dataset_version} | "
            f"{len(run.case_results)}/{len(run.selected_case_ids)} | {link} |"
        )
    failed = [
        result for run in execution.runs for result in run.case_results if result.passed is False
    ]
    if failed:
        lines.extend(["", "**Failed cases**"])
        for result in failed:
            lines.append(f"- `{result.case_id}`: `{', '.join(result.failure_codes)}`")
    if execution.gate_status == "not_evaluated":
        lines.extend(["", "Infrastructure prevented a trustworthy quality verdict."])
    return "\n".join(lines)


LiteralAction = Literal["created", "updated"]
