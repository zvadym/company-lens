from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ScoreScope = Literal["item", "run"]
ScoreDataType = Literal["BOOLEAN", "NUMERIC", "CATEGORICAL"]
ScoreApplicability = Literal[
    "always",
    "citation_required",
    "follow_up",
    "required_tools",
    "prohibited_tools",
    "operational_metrics",
]


class ScoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScoreDefinition(ScoreModel):
    name: str = Field(min_length=1, max_length=35, pattern=r"^[A-Za-z0-9_.() -]+$")
    scope: ScoreScope
    data_type: ScoreDataType
    minimum: float | None = Field(default=None, ge=0, le=1)
    maximum: float | None = Field(default=None, ge=0, le=1)
    categories: tuple[str, ...] = ()
    applicability: ScoreApplicability
    aggregation: str | None = None
    description: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_shape(self) -> ScoreDefinition:
        if self.data_type == "NUMERIC" and (self.minimum is None or self.maximum is None):
            raise ValueError("numeric scores require minimum and maximum")
        if self.data_type == "CATEGORICAL" and not self.categories:
            raise ValueError("categorical scores require categories")
        if self.scope == "run" and self.aggregation is None:
            raise ValueError("run scores require aggregation")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("score minimum cannot exceed maximum")
        return self


class ScoreContract(ScoreModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]*$")
    version: int = Field(ge=1)
    evaluator_version: str = Field(min_length=1)
    scores: tuple[ScoreDefinition, ...] = Field(min_length=1)

    @field_validator("scores")
    @classmethod
    def validate_unique_scores(
        cls,
        scores: tuple[ScoreDefinition, ...],
    ) -> tuple[ScoreDefinition, ...]:
        names = [score.name for score in scores]
        duplicates = sorted({name for name in names if names.count(name) > 1})
        if duplicates:
            raise ValueError(f"duplicate score names: {', '.join(duplicates)}")
        return scores

    @property
    def content_hash(self) -> str:
        payload = self.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(encoded).hexdigest()


def load_score_contract(path: Path) -> ScoreContract:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Score contract must be a YAML mapping.")
    return ScoreContract.model_validate(payload)
