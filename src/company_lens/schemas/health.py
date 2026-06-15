from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ComponentHealth(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"]
    service: str
    version: str
    environment: str
    correlation_id: str | None
    database: ComponentHealth
