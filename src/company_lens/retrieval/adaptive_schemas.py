from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from company_lens.retrieval.schemas import RetrievalFilters

RetrievalStrategy = Literal[
    "none",
    "summary_only",
    "section_level",
    "detailed",
    "structured_only",
    "hybrid",
]
ResolutionStatus = Literal["resolved", "ambiguous", "unresolved"]
EvidenceKind = Literal["document_summary", "section_summary", "chunk", "financial_fact"]


class EntityCandidate(BaseModel):
    id: uuid.UUID | None = None
    canonical_value: str
    display_value: str
    match_kind: str


class EntityResolution(BaseModel):
    kind: str
    mention: str
    status: ResolutionStatus
    canonical_value: str | None = None
    candidates: tuple[EntityCandidate, ...] = ()

    @model_validator(mode="after")
    def _validate_resolution(self) -> EntityResolution:
        if self.status == "resolved" and self.canonical_value is None:
            raise ValueError("resolved entities require a canonical_value")
        if self.status == "ambiguous" and len(self.candidates) < 2:
            raise ValueError("ambiguous entities require at least two candidates")
        return self


class ResolvedQuery(BaseModel):
    query: str
    entities: tuple[EntityResolution, ...] = ()
    company_ids: tuple[uuid.UUID, ...] = ()
    accession_numbers: tuple[str, ...] = ()
    filing_forms: tuple[str, ...] = ()
    fiscal_years: tuple[int, ...] = ()
    fiscal_periods: tuple[str, ...] = ()
    dates: tuple[date, ...] = ()
    metrics: tuple[str, ...] = ()

    @property
    def has_ambiguity(self) -> bool:
        return any(entity.status == "ambiguous" for entity in self.entities)


class RetrievalBudget(BaseModel):
    max_documents: int = Field(default=4, ge=1, le=50)
    max_sections: int = Field(default=8, ge=1, le=100)
    max_chunks: int = Field(default=12, ge=1, le=100)
    max_tokens: int = Field(default=4_000, ge=100, le=100_000)
    max_per_company: int = Field(default=6, ge=1, le=100)
    max_per_period: int = Field(default=4, ge=1, le=100)


class RetrievalPlan(BaseModel):
    query: str
    strategy: RetrievalStrategy
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    budget: RetrievalBudget = Field(default_factory=RetrievalBudget)
    metrics: tuple[str, ...] = ()
    comparative: bool = False
    requires_citations: bool = True
    max_attempts: int = Field(default=3, ge=1, le=5)
    rationale: tuple[str, ...] = ()


class AdaptiveRetrievalRequest(BaseModel):
    query: str = Field(min_length=1)
    max_attempts: int = Field(default=3, ge=1, le=5)
    index_name: str = "default"
    index_version: str = "local-feature-hashing.v1"

    @field_validator("query")
    @classmethod
    def _query_is_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be empty")
        return cleaned


class ContextEvidence(BaseModel):
    kind: EvidenceKind
    content: str
    citation_label: str
    source_url: str
    source_id: str
    company_id: uuid.UUID | None = None
    company_name: str | None = None
    document_version_id: uuid.UUID | None = None
    section_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    financial_fact_id: uuid.UUID | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    page_start: int | None = None
    page_end: int | None = None
    token_count: int = Field(ge=1)


class RetrievalAttempt(BaseModel):
    attempt: int = Field(ge=1)
    strategy: RetrievalStrategy
    action: str
    reason: str | None = None
    evidence_count: int = Field(ge=0)
    context_tokens: int = Field(ge=0)


class RetrievalTrace(BaseModel):
    initial_plan: RetrievalPlan
    attempts: tuple[RetrievalAttempt, ...]
    final_context_tokens: int = Field(ge=0)
    abstained: bool = False
    abstention_reason: str | None = None


class AdaptiveRetrievalResponse(BaseModel):
    query: str
    resolved_query: ResolvedQuery
    plan: RetrievalPlan
    context: tuple[ContextEvidence, ...]
    trace: RetrievalTrace
