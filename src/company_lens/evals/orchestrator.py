from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from company_lens.config import Settings
from company_lens.evals.agent_runner import select_golden_cases
from company_lens.evals.execution_artifacts import materialize_execution_artifacts
from company_lens.evals.execution_runner import execute_preflighted_evaluation
from company_lens.evals.gates import EvaluationGate, load_evaluation_gate
from company_lens.evals.golden import GoldenDataset, GoldenDatasetCase, load_golden_dataset
from company_lens.evals.journal import (
    checkpoint_evaluation_journal,
    initialize_evaluation_journal,
)
from company_lens.evals.langfuse_scores import ReconciledScoreConfigs, reconcile_score_configs
from company_lens.evals.langfuse_sync import LangfuseSyncError, sync_dataset
from company_lens.evals.manifest import (
    ExecutionPolicyManifest,
    LangfuseProjectIdentity,
    WorkflowMetadata,
)
from company_lens.evals.manifest_builder import build_evaluation_manifest
from company_lens.evals.models import (
    EvaluationExecution,
    EvaluationRecoveryJournal,
    ReportingTarget,
)
from company_lens.evals.score_contract import ScoreContract, load_score_contract
from company_lens.observability.langfuse_client import (
    LangfuseClientUnavailable,
    resolve_langfuse_project,
)


@dataclass(frozen=True)
class EvaluationRequest:
    dataset_paths: tuple[Path, ...]
    gate_path: Path
    score_contract_path: Path
    output_dir: Path
    execution_id: UUID = field(default_factory=uuid4)
    max_cases: int | None = None
    max_concurrency: int = 1
    max_tool_calls: int = 10
    max_retries_per_node: int = 2
    max_repair_attempts: int = 1
    session_prefix: str = "golden-eval"
    commit_sha: str = "0000000"
    source_ref: str | None = None
    workflow_run_url: str | None = None
    workflow_actor: str | None = None
    reporting_target: ReportingTarget | None = None


@dataclass(frozen=True)
class EvaluationOutcome:
    exit_code: Literal[0, 1, 2]
    execution: EvaluationExecution
    journal: EvaluationRecoveryJournal


def run_evaluation(
    request: EvaluationRequest,
    *,
    settings: Settings,
    client: Any,
    agent_provider: Callable[[], AbstractContextManager[Any]],
) -> EvaluationOutcome:
    datasets, selected, gate, score_contract = _load_inputs(request)
    journal_path = request.output_dir / "evaluation-journal.json"
    reporting_status: Literal["pending", "not_requested"] = (
        "pending" if request.reporting_target is not None else "not_requested"
    )
    journal = EvaluationRecoveryJournal(
        execution_id=request.execution_id,
        sequence=0,
        updated_at=datetime.now(UTC),
        phase="initialized",
        status="running",
        gate_status="pending",
        reporting_status=reporting_status,
        reporting_target=request.reporting_target,
    )
    initialize_evaluation_journal(journal_path, journal)

    project_identity = _project_identity(client, settings.langfuse_project_id)
    if project_identity.status != "verified":
        manifest = _build_manifest(
            request,
            settings,
            datasets,
            selected,
            gate,
            score_contract,
            project_identity,
            {},
            None,
        )
        return _finish_infrastructure_failure(
            request,
            journal_path,
            journal,
            manifest=manifest,
            project_identity=project_identity,
            code="langfuse_project_unavailable_or_mismatched",
        )
    journal = checkpoint_evaluation_journal(
        journal_path,
        journal,
        phase="project_verified",
        project_identity=project_identity,
    )

    snapshots: dict[str, Any] = {}
    score_configs: ReconciledScoreConfigs | None = None
    try:
        score_configs = reconcile_score_configs(client, score_contract)
        for dataset in datasets:
            result = sync_dataset(
                client,
                dataset,
                score_contract,
                expected_project_id=settings.langfuse_project_id,
            )
            snapshots[dataset.name] = result.snapshot
    except (LangfuseSyncError, RuntimeError, ValueError):
        manifest = _build_manifest(
            request,
            settings,
            datasets,
            selected,
            gate,
            score_contract,
            project_identity,
            snapshots,
            score_configs,
        )
        return _finish_infrastructure_failure(
            request,
            journal_path,
            journal,
            manifest=manifest,
            project_identity=project_identity,
            code="evaluation_preflight_failed",
        )

    manifest = _build_manifest(
        request,
        settings,
        datasets,
        selected,
        gate,
        score_contract,
        project_identity,
        snapshots,
        score_configs,
    )
    assert score_configs is not None
    selected_snapshots = {
        dataset.name: snapshots[dataset.name].model_copy(
            update={"selected_case_ids": tuple(case.id for case in selected[dataset.name])}
        )
        for dataset in datasets
    }
    exit_code, execution, final = execute_preflighted_evaluation(
        execution_id=str(request.execution_id),
        commit_sha=request.commit_sha,
        output_dir=request.output_dir,
        journal_path=journal_path,
        journal=journal,
        manifest=manifest,
        datasets=datasets,
        selected=selected,
        snapshots=selected_snapshots,
        gate=gate,
        score_contract=score_contract,
        score_configs=score_configs,
        client=client,
        agent_provider=agent_provider,
        session_prefix=request.session_prefix,
        max_concurrency=request.max_concurrency,
        max_tool_calls=request.max_tool_calls,
        max_retries_per_node=request.max_retries_per_node,
        max_repair_attempts=request.max_repair_attempts,
        reporting_requested=request.reporting_target is not None,
    )
    return EvaluationOutcome(exit_code=exit_code, execution=execution, journal=final)


def _load_inputs(
    request: EvaluationRequest,
) -> tuple[
    tuple[GoldenDataset, ...],
    dict[str, tuple[GoldenDatasetCase, ...]],
    EvaluationGate,
    ScoreContract,
]:
    datasets = tuple(load_golden_dataset(path) for path in request.dataset_paths)
    if len({dataset.name for dataset in datasets}) != len(datasets):
        raise ValueError("duplicate evaluation datasets")
    selected = {
        dataset.name: select_golden_cases(
            dataset,
            case_ids=(),
            max_cases=request.max_cases,
        )
        for dataset in datasets
    }
    return (
        datasets,
        selected,
        load_evaluation_gate(request.gate_path),
        load_score_contract(request.score_contract_path),
    )


def _project_identity(client: Any, expected_id: str | None) -> LangfuseProjectIdentity:
    checked_at = datetime.now(UTC)
    if not expected_id:
        return LangfuseProjectIdentity(
            expected_project_id=None,
            resolved_project_id=None,
            status="unavailable",
            checked_at=checked_at,
        )
    try:
        project = resolve_langfuse_project(client)
    except LangfuseClientUnavailable:
        return LangfuseProjectIdentity(
            expected_project_id=expected_id,
            resolved_project_id=None,
            status="unavailable",
            checked_at=checked_at,
        )
    return LangfuseProjectIdentity(
        expected_project_id=expected_id,
        resolved_project_id=project.id,
        resolved_project_name=project.name,
        status="verified" if project.id == expected_id else "mismatched",
        checked_at=checked_at,
    )


def _build_manifest(
    request: EvaluationRequest,
    settings: Settings,
    datasets: tuple[GoldenDataset, ...],
    selected: dict[str, tuple[GoldenDatasetCase, ...]],
    gate: EvaluationGate,
    score_contract: ScoreContract,
    project_identity: LangfuseProjectIdentity,
    snapshots: dict[str, Any],
    score_configs: ReconciledScoreConfigs | None,
) -> Any:
    max_cases = request.max_cases or max(len(cases) for cases in selected.values())
    return build_evaluation_manifest(
        execution_id=request.execution_id,
        project_identity=project_identity,
        datasets=datasets,
        selected_cases=selected,
        snapshots=snapshots,
        gate=gate,
        gate_path=request.gate_path,
        score_contract=score_contract,
        score_contract_path=request.score_contract_path,
        score_configs=score_configs,
        settings=settings,
        policy=ExecutionPolicyManifest(
            max_concurrency=request.max_concurrency,
            max_tool_calls=request.max_tool_calls,
            max_retries_per_node=request.max_retries_per_node,
            max_repair_attempts=request.max_repair_attempts,
            max_cases_per_dataset=max_cases,
        ),
        commit_sha=request.commit_sha,
        source_ref=request.source_ref,
        workflow=WorkflowMetadata(
            run_url=request.workflow_run_url,
            actor=request.workflow_actor,
        ),
    )


def _finish_infrastructure_failure(
    request: EvaluationRequest,
    journal_path: Path,
    journal: EvaluationRecoveryJournal,
    *,
    manifest: Any,
    project_identity: LangfuseProjectIdentity,
    code: str,
) -> EvaluationOutcome:
    final = checkpoint_evaluation_journal(
        journal_path,
        journal,
        project_identity=project_identity,
        manifest=manifest,
        phase="reporting" if request.reporting_target is not None else "terminal",
        status="partial" if journal.dataset_runs else "errored",
        gate_status="not_evaluated",
        failure_codes=tuple(dict.fromkeys((*journal.failure_codes, code))),
    )
    execution = materialize_execution_artifacts(final, request.output_dir)
    return EvaluationOutcome(exit_code=2, execution=execution, journal=final)
