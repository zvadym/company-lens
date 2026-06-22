from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class EvidenceKind(enum.StrEnum):
    DOCUMENT = "document"
    FINANCIAL_FACT = "financial_fact"
    MACRO_OBSERVATION = "macro_observation"
    CALCULATION = "calculation"


class SourceStatus(enum.StrEnum):
    AVAILABLE = "available"
    INACCESSIBLE = "inaccessible"
    INVALID = "invalid"
    UNCHECKED = "unchecked"


class SemanticSupportStatus(enum.StrEnum):
    NOT_RUN = "not_run"
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNAVAILABLE = "unavailable"


class EvidenceMetadata(FrozenModel):
    company_id: uuid.UUID | None = None
    company_name: str | None = None
    document_version_id: uuid.UUID | None = None
    section_id: uuid.UUID | None = None
    chunk_id: uuid.UUID | None = None
    financial_fact_id: uuid.UUID | None = None
    macro_observation_id: uuid.UUID | None = None
    metric: str | None = None
    period_start: date | None = None
    period_end: date | None = None
    fiscal_year: int | None = None
    fiscal_period: str | None = None
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    unit: str | None = None
    value: Decimal | None = None
    formula: str | None = None
    operation: str | None = None

    @model_validator(mode="after")
    def validate_ranges(self) -> EvidenceMetadata:
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ValueError("period_start cannot be after period_end.")
        if self.page_start and self.page_end and self.page_start > self.page_end:
            raise ValueError("page_start cannot be after page_end.")
        return self


class EvidenceEnvelope(FrozenModel):
    evidence_id: str = Field(pattern=r"^[a-z][a-z0-9_.:-]*$")
    kind: EvidenceKind
    summary: str = Field(min_length=1)
    source_urls: tuple[str, ...] = ()
    lineage_refs: tuple[str, ...] = ()
    metadata: EvidenceMetadata = Field(default_factory=EvidenceMetadata)
    payload: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_calculation_lineage(self) -> EvidenceEnvelope:
        if self.kind is EvidenceKind.CALCULATION and not self.lineage_refs:
            raise ValueError("Calculation evidence requires input evidence lineage.")
        return self


class ClaimRecord(FrozenModel):
    claim_id: str = Field(pattern=r"^claim:[a-f0-9]{16}$")
    text: str = Field(min_length=1)
    evidence_ids: tuple[str, ...] = ()
    material: bool = True
    sentence_index: int = Field(ge=0)


class CitationReference(FrozenModel):
    evidence_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    claim_ids: tuple[str, ...] = ()


class ValidationIssue(FrozenModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1)
    claim_id: str | None = None
    evidence_id: str | None = None


class SemanticSupportResult(FrozenModel):
    status: SemanticSupportStatus
    reason_code: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    prompt_version: str = Field(min_length=1)
    model: str | None = None


class ClaimValidation(FrozenModel):
    claim_id: str
    supported: bool
    evidence_ids: tuple[str, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()
    semantic_support: SemanticSupportResult | None = None


class AnswerValidation(FrozenModel):
    valid: bool
    claims: tuple[ClaimValidation, ...] = ()
    cited_evidence_ids: tuple[str, ...] = ()
    unknown_evidence_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    issues: tuple[ValidationIssue, ...] = ()


class SourcePreview(FrozenModel):
    evidence_id: str
    title: str
    kind: EvidenceKind
    source_url: str
    exact_url: str
    status: SourceStatus
    page_start: int | None = None
    page_end: int | None = None
    section_id: uuid.UUID | None = None
