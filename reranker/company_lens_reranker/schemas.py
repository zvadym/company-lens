from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RerankItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)

    @field_validator("id", "text")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value must not be blank.")
        return cleaned


class RerankRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    items: tuple[RerankItem, ...] = Field(default_factory=tuple, max_length=500)

    @field_validator("query")
    @classmethod
    def _strip_query(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be blank.")
        return cleaned

    @model_validator(mode="after")
    def _ids_are_unique(self) -> RerankRequest:
        ids = [item.id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("item ids must be unique.")
        return self


class RerankScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    score: float

    @field_validator("id")
    @classmethod
    def _strip_id(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("id must not be blank.")
        return cleaned

    @field_validator("score")
    @classmethod
    def _score_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("score must be finite.")
        return value


class RerankResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str = Field(min_length=1)
    scores: tuple[RerankScore, ...]

    @field_validator("model")
    @classmethod
    def _strip_model(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("model must not be blank.")
        return cleaned


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadyResponse(BaseModel):
    status: Literal["ready"] = "ready"
    model: str = Field(min_length=1)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail
