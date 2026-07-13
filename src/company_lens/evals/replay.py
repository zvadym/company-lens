from __future__ import annotations

import hashlib
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from company_lens.config import Settings
from company_lens.evals.execution_runner import execute_preflighted_evaluation
from company_lens.evals.gates import load_evaluation_gate
from company_lens.evals.golden import GoldenDatasetCase, load_golden_dataset
from company_lens.evals.journal import (
    checkpoint_evaluation_journal,
    initialize_evaluation_journal,
)
from company_lens.evals.langfuse_scores import ReconciledScoreConfigs
from company_lens.evals.langfuse_sync import load_recorded_snapshot
from company_lens.evals.manifest import (
    ComponentVersions,
    EvaluationRunManifest,
    LangfuseProjectIdentity,
    ModelConfigManifest,
    WorkflowMetadata,
    manifest_fingerprint,
)
from company_lens.evals.models import (
    EvaluationExecution,
    EvaluationRecoveryJournal,
    ReportingTarget,
)
from company_lens.evals.orchestrator import EvaluationOutcome
from company_lens.evals.score_contract import load_score_contract
from company_lens.observability.langfuse_client import verify_langfuse_project


class EvaluationReplayError(RuntimeError):
    pass


def replay_evaluation(
    source_execution_path: Path,
    *,
    output_dir: Path,
    execution_id: UUID,
    settings: Settings,
    client: Any,
    agent_provider: Callable[[], AbstractContextManager[Any]],
    session_prefix: str = "golden-eval",
    workflow_run_url: str | None = None,
    workflow_actor: str | None = None,
    reporting_target: ReportingTarget | None = None,
) -> EvaluationOutcome:
    source = _load_source(source_execution_path)
    source_manifest = source.manifest
    if not source_manifest.replay_ready:
        raise EvaluationReplayError("source_manifest_not_replayable")
    datasets = tuple(
        load_golden_dataset(Path(item.source_path)) for item in source_manifest.datasets
    )
    selected: dict[str, tuple[GoldenDatasetCase, ...]] = {}
    snapshots = {}
    for manifest_dataset, dataset in zip(source_manifest.datasets, datasets, strict=True):
        if dataset.content_hash != manifest_dataset.repository_hash:
            raise EvaluationReplayError("replay_dataset_hash_mismatch")
        cases = {case.id: case for case in dataset.cases}
        try:
            selected[dataset.name] = tuple(
                cases[case_id] for case_id in manifest_dataset.selected_case_ids
            )
        except KeyError as exc:
            raise EvaluationReplayError("replay_dataset_case_mismatch") from exc
        if manifest_dataset.snapshot is None:
            raise EvaluationReplayError("replay_snapshot_missing")
        snapshots[dataset.name] = manifest_dataset.snapshot

    gate_path = Path(source_manifest.gate.source_path)
    if _file_hash(gate_path) != source_manifest.gate.content_hash:
        raise EvaluationReplayError("replay_gate_hash_mismatch")
    gate = load_evaluation_gate(gate_path)
    score_path = Path(source_manifest.score_contract.source_path)
    score_contract = load_score_contract(score_path)
    if score_contract.content_hash != source_manifest.score_contract.content_hash:
        raise EvaluationReplayError("replay_score_contract_hash_mismatch")
    _validate_runtime_settings(settings, source_manifest)

    journal_path = output_dir / "evaluation-journal.json"
    reporting_status: Literal["pending", "not_requested"] = (
        "pending" if reporting_target is not None else "not_requested"
    )
    journal = EvaluationRecoveryJournal(
        execution_id=execution_id,
        sequence=0,
        updated_at=datetime.now(UTC),
        phase="initialized",
        status="running",
        gate_status="pending",
        reporting_status=reporting_status,
        reporting_target=reporting_target,
    )
    initialize_evaluation_journal(journal_path, journal)
    project = verify_langfuse_project(client, settings.langfuse_project_id)
    project_identity = LangfuseProjectIdentity(
        expected_project_id=settings.langfuse_project_id,
        resolved_project_id=project.id,
        resolved_project_name=project.name,
        status="verified",
        checked_at=datetime.now(UTC),
    )
    journal = checkpoint_evaluation_journal(
        journal_path,
        journal,
        phase="project_verified",
        project_identity=project_identity,
    )
    for snapshot in snapshots.values():
        load_recorded_snapshot(
            client,
            snapshot,
            expected_project_id=settings.langfuse_project_id,
        )

    replay_manifest = _replay_manifest(
        source,
        execution_id=execution_id,
        project_identity=project_identity,
        workflow=WorkflowMetadata(run_url=workflow_run_url, actor=workflow_actor),
    )
    bindings = ReconciledScoreConfigs(bindings=source_manifest.score_contract.config_bindings)
    exit_code, execution, final = execute_preflighted_evaluation(
        execution_id=str(execution_id),
        commit_sha=source_manifest.commit_sha,
        output_dir=output_dir,
        journal_path=journal_path,
        journal=journal,
        manifest=replay_manifest,
        datasets=datasets,
        selected=selected,
        snapshots=snapshots,
        gate=gate,
        score_contract=score_contract,
        score_configs=bindings,
        client=client,
        agent_provider=agent_provider,
        session_prefix=session_prefix,
        max_concurrency=source_manifest.execution_policy.max_concurrency,
        max_tool_calls=source_manifest.execution_policy.max_tool_calls,
        max_retries_per_node=source_manifest.execution_policy.max_retries_per_node,
        max_repair_attempts=source_manifest.execution_policy.max_repair_attempts,
        reporting_requested=reporting_target is not None,
    )
    return EvaluationOutcome(exit_code=exit_code, execution=execution, journal=final)


def _load_source(path: Path) -> EvaluationExecution:
    try:
        source = EvaluationExecution.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise EvaluationReplayError("source_execution_invalid") from exc
    if source.status not in {"completed", "partial"}:
        raise EvaluationReplayError("source_execution_not_replayable")
    return source


def _replay_manifest(
    source: EvaluationExecution,
    *,
    execution_id: UUID,
    project_identity: LangfuseProjectIdentity,
    workflow: WorkflowMetadata,
) -> EvaluationRunManifest:
    payload = source.manifest.model_dump(mode="json")
    payload.update(
        {
            "execution_id": str(execution_id),
            "replay_of_execution_id": str(source.execution_id),
            "source_manifest_fingerprint": source.manifest.manifest_fingerprint,
            "manifest_fingerprint": "0" * 64,
            "project_identity": project_identity.model_dump(mode="json"),
            "workflow": workflow.model_dump(mode="json"),
        }
    )
    payload["manifest_fingerprint"] = manifest_fingerprint(payload)
    return EvaluationRunManifest.model_validate(payload)


def _validate_runtime_settings(settings: Settings, manifest: EvaluationRunManifest) -> None:
    current_models = (
        ModelConfigManifest(
            purpose="planning",
            name=settings.openai_planning_model,
            reasoning_effort=settings.openai_planning_reasoning_effort,
            max_output_tokens=settings.openai_planning_max_output_tokens,
        ),
        ModelConfigManifest(
            purpose="answer",
            name=settings.openai_answer_model,
            reasoning_effort=settings.openai_answer_reasoning_effort,
            max_output_tokens=settings.openai_answer_max_output_tokens,
        ),
        ModelConfigManifest(
            purpose="repair",
            name=settings.openai_repair_model,
            reasoning_effort=settings.openai_repair_reasoning_effort,
            max_output_tokens=settings.openai_repair_max_output_tokens,
        ),
    )
    versions = ComponentVersions(
        parser=settings.parser_version,
        embedding_model=settings.openai_embedding_model,
        retrieval_index=settings.agent_retrieval_index_version,
    )
    if current_models != manifest.models or versions != manifest.versions:
        raise EvaluationReplayError("replay_runtime_mismatch")


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise EvaluationReplayError("replay_input_unavailable") from exc
