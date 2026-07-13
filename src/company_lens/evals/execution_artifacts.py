from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

from company_lens.evals.journal import (
    atomic_write,
    checkpoint_evaluation_journal,
    load_evaluation_journal,
)
from company_lens.evals.models import (
    ArtifactPaths,
    DatasetEvaluationRun,
    EvaluationExecution,
    EvaluationRecoveryJournal,
)

FORBIDDEN_ARTIFACT_KEYS = frozenset(
    {
        "api_key",
        "credentials",
        "evidence_passage",
        "exception_text",
        "final_answer",
        "provider_payload",
        "raw_answer",
        "raw_prompt",
        "secret",
        "stack_trace",
    }
)


def materialize_execution_artifacts(
    journal: EvaluationRecoveryJournal,
    output_dir: Path,
) -> EvaluationExecution:
    if journal.manifest is None or journal.status == "running":
        raise ValueError("terminal journal with a frozen manifest is required")
    runs = journal.dataset_runs or tuple(
        DatasetEvaluationRun(
            dataset_name=dataset.dataset_name,
            dataset_version=dataset.repository_version,
            snapshot=dataset.snapshot,
            status="errored",
            gate_status="not_evaluated",
            selected_case_ids=dataset.selected_case_ids,
        )
        for dataset in journal.manifest.datasets
    )
    paths = ArtifactPaths(
        journal="evaluation-journal.json",
        json="evaluation-execution.json",
        markdown="evaluation-summary.md",
    )
    execution = EvaluationExecution(
        execution_id=journal.execution_id,
        started_at=journal.manifest.project_identity.checked_at,
        completed_at=journal.updated_at,
        status=journal.status,
        gate_status=cast(
            Literal["passed", "failed", "not_evaluated"],
            journal.gate_status,
        ),
        manifest=journal.manifest,
        runs=runs,
        failure_codes=journal.failure_codes,
        artifact_paths=paths,
    )
    payload = execution.model_dump(mode="json", by_alias=True)
    _guard_forbidden_keys(payload)
    atomic_write(
        output_dir / paths.json_path,
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )
    atomic_write(output_dir / paths.markdown, format_execution_summary(execution) + "\n")
    return execution


def recover_evaluation_artifacts(
    journal_path: Path,
    output_dir: Path | None = None,
) -> tuple[EvaluationRecoveryJournal, EvaluationExecution]:
    journal = load_evaluation_journal(journal_path)
    destination = output_dir or journal_path.parent
    if journal.status == "running":
        journal = checkpoint_evaluation_journal(
            journal_path,
            journal,
            phase="reporting" if journal.reporting_target is not None else "terminal",
            status="partial" if journal.dataset_runs else "errored",
            gate_status="not_evaluated",
            failure_codes=tuple(dict.fromkeys((*journal.failure_codes, "evaluation_interrupted"))),
        )
    execution = materialize_execution_artifacts(journal, destination)
    return journal, execution


def format_execution_summary(execution: EvaluationExecution) -> str:
    lines = [
        "# Evaluation Summary",
        "",
        f"- Execution: `{execution.execution_id}`",
        f"- Commit: `{execution.manifest.commit_sha}`",
        f"- Status: `{execution.status}`",
        f"- Gate: `{execution.gate_status}`",
        "",
        "## Dataset Runs",
        "",
        "| Dataset | Status | Gate | Cases | Langfuse |",
        "| --- | --- | --- | ---: | --- |",
    ]
    for run in execution.runs:
        link = f"[open run]({run.langfuse_run_url})" if run.langfuse_run_url else "unavailable"
        lines.append(
            f"| `{run.dataset_name}` | `{run.status}` | `{run.gate_status}` | "
            f"{len(run.case_results)}/{len(run.selected_case_ids)} | {link} |"
        )
    failed = [
        result for run in execution.runs for result in run.case_results if result.passed is False
    ]
    if failed:
        lines.extend(["", "## Failed Cases", ""])
        for result in failed:
            codes = ", ".join(result.failure_codes) or "deterministic_check_failed"
            lines.append(f"- `{result.case_id}`: `{codes}`")
    if execution.failure_codes:
        lines.extend(["", "## Infrastructure", ""])
        lines.extend(f"- `{code}`" for code in execution.failure_codes)
    return "\n".join(lines)


def _guard_forbidden_keys(value: object) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_ARTIFACT_KEYS & set(value)
        if forbidden:
            raise ValueError(f"forbidden artifact fields: {', '.join(sorted(forbidden))}")
        for nested in value.values():
            _guard_forbidden_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            _guard_forbidden_keys(nested)
