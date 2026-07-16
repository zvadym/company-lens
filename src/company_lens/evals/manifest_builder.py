from __future__ import annotations

import hashlib
from pathlib import Path
from uuid import UUID

from company_lens.config import Settings
from company_lens.evals.gates import EvaluationGate
from company_lens.evals.golden import GoldenDataset, GoldenDatasetCase
from company_lens.evals.langfuse_scores import ReconciledScoreConfigs
from company_lens.evals.manifest import (
    ComponentVersions,
    DatasetSnapshot,
    EvaluationRunManifest,
    ExecutionPolicyManifest,
    GateManifest,
    LangfuseProjectIdentity,
    ManifestDataset,
    ModelConfigManifest,
    ScoreContractManifest,
    WorkflowMetadata,
    manifest_fingerprint,
)
from company_lens.evals.score_contract import ScoreContract


def build_evaluation_manifest(
    *,
    execution_id: UUID,
    project_identity: LangfuseProjectIdentity,
    datasets: tuple[GoldenDataset, ...],
    selected_cases: dict[str, tuple[GoldenDatasetCase, ...]],
    snapshots: dict[str, DatasetSnapshot],
    gate: EvaluationGate,
    gate_path: Path,
    score_contract: ScoreContract,
    score_contract_path: Path,
    score_configs: ReconciledScoreConfigs | None,
    settings: Settings,
    policy: ExecutionPolicyManifest,
    commit_sha: str,
    source_ref: str | None,
    workflow: WorkflowMetadata,
    replay_of_execution_id: UUID | None = None,
    source_manifest_fingerprint: str | None = None,
) -> EvaluationRunManifest:
    manifest_datasets = tuple(
        _manifest_dataset(dataset, selected_cases[dataset.name], snapshots.get(dataset.name))
        for dataset in datasets
    )
    draft = EvaluationRunManifest(
        execution_id=execution_id,
        replay_of_execution_id=replay_of_execution_id,
        source_manifest_fingerprint=source_manifest_fingerprint,
        manifest_fingerprint="0" * 64,
        commit_sha=commit_sha,
        source_ref=source_ref,
        environment=settings.environment,
        service_version=settings.service_version,
        project_identity=project_identity,
        datasets=manifest_datasets,
        gate=GateManifest(
            name=gate.name,
            version=gate.version,
            source_path=gate_path.as_posix(),
            content_hash=_file_hash(gate_path),
        ),
        score_contract=ScoreContractManifest(
            name=score_contract.name,
            version=score_contract.version,
            source_path=score_contract_path.as_posix(),
            content_hash=score_contract.content_hash,
            config_status="verified" if score_configs is not None else "failed",
            config_bindings=score_configs.bindings if score_configs is not None else (),
        ),
        models=_model_configs(settings),
        versions=ComponentVersions(
            parser=settings.parser_version,
            embedding_model=settings.openai_embedding_model,
            retrieval_index=settings.agent_retrieval_index_version,
        ),
        execution_policy=policy,
        workflow=workflow,
    )
    fingerprint = manifest_fingerprint(draft.model_dump(mode="json"))
    return draft.model_copy(update={"manifest_fingerprint": fingerprint})


def _manifest_dataset(
    dataset: GoldenDataset,
    selected: tuple[GoldenDatasetCase, ...],
    snapshot: DatasetSnapshot | None,
) -> ManifestDataset:
    if dataset.source_path is None or dataset.content_hash is None:
        raise ValueError("source-aware golden dataset is required")
    selected_ids = tuple(case.id for case in selected)
    selected_snapshot = (
        snapshot.model_copy(update={"selected_case_ids": selected_ids})
        if snapshot is not None
        else None
    )
    return ManifestDataset(
        dataset_name=dataset.name,
        repository_version=dataset.version,
        source_path=dataset.source_path.as_posix(),
        repository_hash=dataset.content_hash,
        selected_case_ids=selected_ids,
        preflight_status="verified" if selected_snapshot is not None else "failed",
        snapshot=selected_snapshot,
    )


def _model_configs(settings: Settings) -> tuple[ModelConfigManifest, ...]:
    return (
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


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
