from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from company_lens.agent.output import ResearchCitationOutput, ResearchExecutionOutput
from company_lens.agent.schemas import AgentError, AgentRunStatus, ExecutionPolicy
from company_lens.analytics.schemas import ChartSpecification
from company_lens.evidence.schemas import SourcePreview


class ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)


class ResearchRunStatus(enum.StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    CANCELLATION_REQUESTED = "cancellation_requested"
    COMPLETED = "completed"
    PARTIAL = "partial"
    ABSTAINED = "abstained"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def terminal(self) -> bool:
        return self in {
            self.COMPLETED,
            self.PARTIAL,
            self.ABSTAINED,
            self.FAILED,
            self.CANCELLED,
            self.TIMED_OUT,
        }


class StartResearchRequest(ApiModel):
    question: str = Field(min_length=1, max_length=4_000)
    session_id: str | None = Field(
        default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"
    )
    policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        cleaned = " ".join(value.split())
        if not cleaned:
            raise ValueError("question cannot be blank")
        return cleaned


class ResearchAccepted(ApiModel):
    run_id: uuid.UUID
    session_id: str
    status: Literal[ResearchRunStatus.QUEUED] = ResearchRunStatus.QUEUED
    run_url: str
    events_url: str
    sources_url: str


class ResearchResult(ApiModel):
    agent_status: AgentRunStatus
    answer: str | None = None
    citations: tuple[ResearchCitationOutput, ...] = ()
    chart: ChartSpecification | None = None
    warnings: tuple[AgentError, ...] = ()
    execution: ResearchExecutionOutput
    sources: tuple[SourcePreview, ...] = ()


class ResearchRunResponse(ApiModel):
    run_id: uuid.UUID
    session_id: str
    status: ResearchRunStatus
    question: str
    result: ResearchResult | None = None
    error_code: str | None = None
    error_message: str | None = None
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    deadline_at: datetime
    cancellation_requested_at: datetime | None = None


class ResearchSourcesResponse(ApiModel):
    run_id: uuid.UUID
    sources: tuple[SourcePreview, ...] = ()


class FeedbackRequest(ApiModel):
    run_id: uuid.UUID
    rating: Literal["positive", "negative"]
    comment: str | None = Field(default=None, max_length=2_000)
    actor_id: str | None = Field(default=None, min_length=1, max_length=128)


class FeedbackResponse(ApiModel):
    feedback_id: uuid.UUID
    run_id: uuid.UUID
    rating: Literal["positive", "negative"]
    created_at: datetime


class CompanyOutput(ApiModel):
    id: uuid.UUID
    display_name: str
    legal_name: str
    cik: str | None = None
    primary_ticker: str | None = None
    exchange: str | None = None


class CompaniesResponse(ApiModel):
    items: tuple[CompanyOutput, ...]
    total: int


ResearchEventType = Literal[
    "run.status",
    "node.status",
    "tool.call",
    "retrieval.summary",
    "chart.ready",
    "answer.token",
    "run.terminal",
]


class ResearchEventEnvelope(ApiModel):
    id: int
    schema_version: Literal["1"] = "1"
    run_id: uuid.UUID
    type: ResearchEventType
    occurred_at: datetime
    data: dict[str, Any]


class PublicErrorDetail(ApiModel):
    code: str
    message: str
    correlation_id: str | None = None


class PublicErrorResponse(ApiModel):
    error: PublicErrorDetail
