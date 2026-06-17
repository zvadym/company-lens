from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from company_lens.db.models import DocumentKind

RetrievalMode = Literal["dense", "lexical", "hybrid"]


class RetrievalFilters(BaseModel):
    company_ids: tuple[uuid.UUID, ...] = ()
    document_version_ids: tuple[uuid.UUID, ...] = ()
    document_kinds: tuple[DocumentKind, ...] = ()
    filing_forms: tuple[str, ...] = ()
    filing_date_from: date | None = None
    filing_date_to: date | None = None
    period_end_from: date | None = None
    period_end_to: date | None = None
    fiscal_years: tuple[int, ...] = ()
    fiscal_periods: tuple[str, ...] = ()
    section_codes: tuple[str, ...] = ()
    source_systems: tuple[str, ...] = ()

    @field_validator("filing_forms", "fiscal_periods", "section_codes", "source_systems")
    @classmethod
    def _strip_strings(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(value.strip() for value in values if value.strip())


class RetrievalRequest(BaseModel):
    query: str
    mode: RetrievalMode = "hybrid"
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    index_name: str = "default"
    index_version: str = "local-feature-hashing.v1"
    top_k: int = Field(default=10, ge=1, le=100)
    dense_candidate_limit: int = Field(default=50, ge=1, le=500)
    lexical_candidate_limit: int = Field(default=50, ge=1, le=500)
    max_per_document: int = Field(default=3, ge=1, le=100)
    max_per_period: int = Field(default=4, ge=1, le=100)
    include_parent_text: bool = False
    near_duplicate_threshold: float = Field(default=0.92, ge=0.0, le=1.0)

    @field_validator("query")
    @classmethod
    def _query_is_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query must not be empty.")
        return cleaned


class EmbeddingIndexingRequest(BaseModel):
    index_name: str = "default"
    index_version: str = "local-feature-hashing.v1"
    limit: int | None = Field(default=None, ge=1)
    batch_size: int = Field(default=100, ge=1, le=1000)
    force: bool = False


class EmbeddingIndexingResult(BaseModel):
    index_id: uuid.UUID
    index_name: str
    index_version: str
    embedding_model: str
    dimensions: int
    indexed: int
    skipped: int
    stale_rebuilt: int
    failed: int


class RetrievalScores(BaseModel):
    lexical_score: float | None = None
    vector_score: float | None = None
    reranker_score: float | None = None
    hybrid_score: float | None = None


class RetrievalDiagnostics(BaseModel):
    selected_strategy: RetrievalMode
    rank: int
    dense_rank: int | None = None
    lexical_rank: int | None = None
    reranker_rank: int | None = None
    embedding_index_name: str | None = None
    embedding_index_version: str | None = None
    embedding_model: str | None = None
    dedupe_removed: bool = False
    diversity_limited: bool = False
    matched_filters: dict[str, object] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()


class RetrievalResult(BaseModel):
    chunk_id: uuid.UUID
    source_document_id: uuid.UUID
    document_version_id: uuid.UUID
    section_id: uuid.UUID
    company_id: uuid.UUID | None = None
    company_display_name: str | None = None
    document_title: str | None = None
    document_kind: str
    source_system: str
    stable_source_id: str
    source_url: str
    accession_number: str | None = None
    filing_form: str | None = None
    filing_date: date | None = None
    period_end: date | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    section_code: str | None = None
    section_title: str
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    chunk_index: int
    text: str
    content_hash: str
    section_summary: str | None = None
    document_summary: str | None = None
    scores: RetrievalScores
    diagnostics: RetrievalDiagnostics


class RetrievalResponse(BaseModel):
    query: str
    mode: RetrievalMode
    results: tuple[RetrievalResult, ...]
    diagnostics: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _result_count_matches_diagnostics(self) -> RetrievalResponse:
        self.diagnostics.setdefault("result_count", len(self.results))
        return self
