from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Sha256 = str


class ManifestModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class LangfuseProjectIdentity(ManifestModel):
    expected_project_id: str | None
    resolved_project_id: str | None
    resolved_project_name: str | None = None
    status: Literal["verified", "mismatched", "unavailable"]
    checked_at: datetime

    @model_validator(mode="after")
    def validate_ids(self) -> LangfuseProjectIdentity:
        if self.status in {"verified", "mismatched"} and (
            not self.expected_project_id or not self.resolved_project_id
        ):
            raise ValueError("verified or mismatched project identity requires both IDs")
        if self.status == "verified" and self.expected_project_id != self.resolved_project_id:
            raise ValueError("verified project identity IDs must match")
        if self.status == "mismatched" and self.expected_project_id == self.resolved_project_id:
            raise ValueError("mismatched project identity IDs must differ")
        return self


class DatasetSnapshot(ManifestModel):
    dataset_name: str = Field(min_length=1)
    repository_version: int = Field(ge=1)
    source_path: str = Field(min_length=1)
    repository_hash: Sha256 = Field(pattern=r"^[a-f0-9]{64}$")
    langfuse_project_id: str = Field(min_length=1)
    langfuse_dataset_id: str = Field(min_length=1)
    version_timestamp: datetime
    active_item_ids: tuple[str, ...] = Field(min_length=1)
    active_item_hashes: dict[str, Sha256]
    stale_item_ids: tuple[str, ...] = ()
    selected_case_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_items(self) -> DatasetSnapshot:
        if len(set(self.active_item_ids)) != len(self.active_item_ids):
            raise ValueError("active item IDs must be unique")
        if set(self.active_item_ids) != set(self.active_item_hashes):
            raise ValueError("active item hashes must match active item IDs")
        return self


class ManifestDataset(ManifestModel):
    dataset_name: str
    repository_version: int = Field(ge=1)
    source_path: str
    repository_hash: Sha256 = Field(pattern=r"^[a-f0-9]{64}$")
    selected_case_ids: tuple[str, ...] = Field(min_length=1)
    preflight_status: Literal["verified", "failed"]
    snapshot: DatasetSnapshot | None = None

    @model_validator(mode="after")
    def validate_snapshot(self) -> ManifestDataset:
        if (self.preflight_status == "verified") != (self.snapshot is not None):
            raise ValueError("verified dataset preflight requires exactly one snapshot")
        return self


class GateManifest(ManifestModel):
    name: str
    version: int = Field(ge=1)
    source_path: str
    content_hash: Sha256 = Field(pattern=r"^[a-f0-9]{64}$")


class ScoreConfigBinding(ManifestModel):
    score_name: str = Field(min_length=1, max_length=35)
    langfuse_config_id: str = Field(min_length=1)


class ScoreContractManifest(ManifestModel):
    name: str
    version: int = Field(ge=1)
    source_path: str
    content_hash: Sha256 = Field(pattern=r"^[a-f0-9]{64}$")
    config_status: Literal["verified", "failed"]
    config_bindings: tuple[ScoreConfigBinding, ...] = ()

    @model_validator(mode="after")
    def validate_bindings(self) -> ScoreContractManifest:
        if self.config_status == "verified" and not self.config_bindings:
            raise ValueError("verified score contract requires config bindings")
        if self.config_status == "failed" and self.config_bindings:
            raise ValueError("failed score contract cannot include config bindings")
        return self


class ModelConfigManifest(ManifestModel):
    purpose: Literal["planning", "answer", "repair"]
    name: str
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh"]
    max_output_tokens: int = Field(ge=1)


class PromptVersionManifest(ManifestModel):
    name: str
    source: str
    version: str
    content_hash: Sha256 = Field(pattern=r"^[a-f0-9]{64}$")


class ComponentVersions(ManifestModel):
    parser: str
    embedding_model: str
    retrieval_index: str


class ExecutionPolicyManifest(ManifestModel):
    max_concurrency: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)
    max_retries_per_node: int = Field(ge=0)
    max_repair_attempts: int = Field(ge=0)
    max_cases_per_dataset: int = Field(ge=1)


class WorkflowMetadata(ManifestModel):
    run_url: str | None = None
    actor: str | None = None


class EvaluationRunManifest(ManifestModel):
    schema_version: Literal[1] = 1
    execution_id: UUID
    replay_of_execution_id: UUID | None = None
    source_manifest_fingerprint: Sha256 | None = None
    manifest_fingerprint: Sha256 = Field(pattern=r"^[a-f0-9]{64}$")
    commit_sha: str = Field(pattern=r"^[a-fA-F0-9]{7,40}$")
    source_ref: str | None = None
    environment: str
    service_version: str
    project_identity: LangfuseProjectIdentity
    datasets: tuple[ManifestDataset, ...] = Field(min_length=1)
    gate: GateManifest
    score_contract: ScoreContractManifest
    models: tuple[ModelConfigManifest, ...] = Field(min_length=3, max_length=3)
    prompts: tuple[PromptVersionManifest, ...] = ()
    versions: ComponentVersions
    execution_policy: ExecutionPolicyManifest
    workflow: WorkflowMetadata

    @model_validator(mode="after")
    def validate_replay(self) -> EvaluationRunManifest:
        if (self.replay_of_execution_id is None) != (self.source_manifest_fingerprint is None):
            raise ValueError("replay source ID and fingerprint must be supplied together")
        if len({model.purpose for model in self.models}) != 3:
            raise ValueError("manifest requires planning, answer, and repair model configs")
        if self.replay_of_execution_id is not None and not self.replay_ready:
            raise ValueError(
                "replay manifest requires verified project, datasets, and score configs"
            )
        return self

    @property
    def replay_ready(self) -> bool:
        return (
            self.project_identity.status == "verified"
            and all(dataset.preflight_status == "verified" for dataset in self.datasets)
            and self.score_contract.config_status == "verified"
        )


def manifest_fingerprint(payload: dict[str, object]) -> str:
    canonical = dict(payload)
    canonical.pop("manifest_fingerprint", None)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()
