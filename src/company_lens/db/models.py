from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from company_lens.db.base import Base
from company_lens.db.types import PgVector

JsonObject = dict[str, Any]
JSON_TYPE = JSONB().with_variant(JSON(), "sqlite")


class AliasKind(enum.StrEnum):
    LEGAL = "legal"
    BRAND = "brand"
    FORMER = "former"
    COMMON = "common"


class IdentifierKind(enum.StrEnum):
    CIK = "cik"
    LEI = "lei"
    CUSIP = "cusip"
    ISIN = "isin"
    SEC_ENTITY_ID = "sec_entity_id"
    OTHER = "other"


class DocumentKind(enum.StrEnum):
    SEC_FILING = "sec_filing"
    INVESTOR_PDF = "investor_pdf"
    SEC_COMPANY_FACTS = "sec_company_facts"
    MACRO_SERIES = "macro_series"
    OTHER = "other"


class DocumentVersionState(enum.StrEnum):
    CURRENT = "current"
    SUPERSEDED = "superseded"
    RESTATED = "restated"


class IngestionRunStatus(enum.StrEnum):
    STARTED = "started"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PARTIAL = "partial"


class ArtifactKind(enum.StrEnum):
    RAW_HTML = "raw_html"
    RAW_TEXT = "raw_text"
    RAW_PDF = "raw_pdf"
    PAGE_IMAGE = "page_image"
    EXTRACTED_TEXT = "extracted_text"
    OTHER = "other"


class EvidenceKind(enum.StrEnum):
    SECTION = "section"
    CHUNK = "chunk"
    PAGE = "page"
    FACT = "fact"
    MACRO_OBSERVATION = "macro_observation"
    CALCULATION = "calculation"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    cik: Mapped[str | None] = mapped_column(String(10), unique=True)
    country_code: Mapped[str | None] = mapped_column(String(2))
    fiscal_year_end: Mapped[str | None] = mapped_column(String(5))

    aliases: Mapped[list[CompanyAlias]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    identifiers: Mapped[list[CompanyIdentifier]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    tickers: Mapped[list[CompanyTicker]] = relationship(
        back_populates="company",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list[SourceDocument]] = relationship(back_populates="company")
    facts: Mapped[list[FinancialFact]] = relationship(back_populates="company")


class CompanyAlias(Base, TimestampMixin):
    __tablename__ = "company_aliases"
    __table_args__ = (UniqueConstraint("company_id", "alias", name="uq_company_alias"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), nullable=False)
    alias: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[AliasKind] = mapped_column(
        Enum(AliasKind, name="alias_kind"),
        nullable=False,
        default=AliasKind.COMMON,
    )

    company: Mapped[Company] = relationship(back_populates="aliases")


class CompanyIdentifier(Base, TimestampMixin):
    __tablename__ = "company_identifiers"
    __table_args__ = (UniqueConstraint("kind", "value", name="uq_company_identifier_kind_value"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), nullable=False)
    kind: Mapped[IdentifierKind] = mapped_column(Enum(IdentifierKind, name="identifier_kind"))
    value: Mapped[str] = mapped_column(String(128), nullable=False)
    source: Mapped[str | None] = mapped_column(String(128))
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)

    company: Mapped[Company] = relationship(back_populates="identifiers")


class Exchange(Base, TimestampMixin):
    __tablename__ = "exchanges"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    mic: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country_code: Mapped[str | None] = mapped_column(String(2))

    tickers: Mapped[list[CompanyTicker]] = relationship(back_populates="exchange")


class CompanyTicker(Base, TimestampMixin):
    __tablename__ = "company_tickers"
    __table_args__ = (
        UniqueConstraint("exchange_id", "symbol", "valid_from", name="uq_ticker_exchange_period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), nullable=False)
    exchange_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exchanges.id"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)

    company: Mapped[Company] = relationship(back_populates="tickers")
    exchange: Mapped[Exchange] = relationship(back_populates="tickers")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[IngestionRunStatus] = mapped_column(
        Enum(IngestionRunStatus, name="ingestion_run_status"),
        nullable=False,
        default=IngestionRunStatus.STARTED,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    code_version: Mapped[str | None] = mapped_column(String(64))
    config_hash: Mapped[str | None] = mapped_column(String(128))
    parameters: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)

    document_versions: Mapped[list[DocumentVersion]] = relationship(back_populates="ingestion_run")
    macro_observations: Mapped[list[MacroObservation]] = relationship(
        back_populates="ingestion_run"
    )
    failures: Mapped[list[IngestionFailure]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
    )


class IngestionFailure(Base):
    __tablename__ = "ingestion_failures"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ingestion_runs.id"), nullable=False)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_documents.id"))
    stage: Mapped[str] = mapped_column(String(128), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    details_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    run: Mapped[IngestionRun] = relationship(back_populates="failures")
    company: Mapped[Company | None] = relationship()
    source_document: Mapped[SourceDocument | None] = relationship()


class ResearchSession(Base):
    __tablename__ = "research_sessions"

    session_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    turn_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    active_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SourceDocument(Base, TimestampMixin):
    __tablename__ = "source_documents"
    __table_args__ = (
        UniqueConstraint("source_system", "stable_source_id", name="uq_document_stable_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("companies.id"))
    kind: Mapped[DocumentKind] = mapped_column(Enum(DocumentKind, name="document_kind"))
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    stable_source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String(512))
    accession_number: Mapped[str | None] = mapped_column(String(64))
    filing_form: Mapped[str | None] = mapped_column(String(32))
    filing_date: Mapped[date | None] = mapped_column(Date)
    report_date: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(16))
    metadata_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)

    company: Mapped[Company | None] = relationship(back_populates="documents")
    versions: Mapped[list[DocumentVersion]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
    )


class DocumentVersion(Base, TimestampMixin):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("document_id", "content_hash", name="uq_document_version_hash"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_documents.id"), nullable=False
    )
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    version_label: Mapped[str] = mapped_column(String(128), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source_hash: Mapped[str | None] = mapped_column(String(128))
    artifact_uri: Mapped[str | None] = mapped_column(Text)
    state: Mapped[DocumentVersionState] = mapped_column(
        Enum(DocumentVersionState, name="document_version_state"),
        nullable=False,
        default=DocumentVersionState.CURRENT,
    )
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id")
    )
    metadata_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)

    document: Mapped[SourceDocument] = relationship(back_populates="versions")
    ingestion_run: Mapped[IngestionRun | None] = relationship(back_populates="document_versions")
    supersedes_version: Mapped[DocumentVersion | None] = relationship(remote_side=[id])
    summaries: Mapped[list[DocumentSummary]] = relationship(
        back_populates="document_version",
        cascade="all, delete-orphan",
    )
    sections: Mapped[list[FilingSection]] = relationship(
        back_populates="document_version",
        cascade="all, delete-orphan",
    )
    pages: Mapped[list[PdfPage]] = relationship(
        back_populates="document_version",
        cascade="all, delete-orphan",
    )
    pdf_blocks: Mapped[list[PdfBlock]] = relationship(
        back_populates="document_version",
        cascade="all, delete-orphan",
    )
    artifacts: Mapped[list[SourceArtifact]] = relationship(
        back_populates="document_version",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(back_populates="document_version")


class DocumentSummary(Base, TimestampMixin):
    __tablename__ = "document_summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"),
        nullable=False,
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="summaries")


class FilingSection(Base, TimestampMixin):
    __tablename__ = "filing_sections"
    __table_args__ = (
        UniqueConstraint("document_version_id", "ordinal_path", name="uq_section_ordinal_path"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"),
        nullable=False,
    )
    parent_section_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("filing_sections.id"))
    source_section_id: Mapped[str | None] = mapped_column(String(128))
    section_code: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    ordinal_path: Mapped[str] = mapped_column(String(128), nullable=False)
    heading_level: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="sections")
    parent_section: Mapped[FilingSection | None] = relationship(
        remote_side=[id],
        back_populates="child_sections",
    )
    child_sections: Mapped[list[FilingSection]] = relationship(back_populates="parent_section")
    summaries: Mapped[list[SectionSummary]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
    )
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
    )


class SectionSummary(Base, TimestampMixin):
    __tablename__ = "section_summaries"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("filing_sections.id"), nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_hash: Mapped[str | None] = mapped_column(String(128))
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    metadata_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)

    section: Mapped[FilingSection] = relationship(back_populates="summaries")


class PdfPage(Base, TimestampMixin):
    __tablename__ = "pdf_pages"
    __table_args__ = (
        UniqueConstraint("document_version_id", "page_number", name="uq_pdf_page_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"),
        nullable=False,
    )
    page_number: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str | None] = mapped_column(String(128))
    image_uri: Mapped[str | None] = mapped_column(Text)
    width_points: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    height_points: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))

    document_version: Mapped[DocumentVersion] = relationship(back_populates="pages")
    blocks: Mapped[list[PdfBlock]] = relationship(
        back_populates="page",
        cascade="all, delete-orphan",
    )


class PdfBlock(Base, TimestampMixin):
    __tablename__ = "pdf_blocks"
    __table_args__ = (UniqueConstraint("page_id", "block_index", name="uq_pdf_block_page_index"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"),
        nullable=False,
    )
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pdf_pages.id"), nullable=False)
    block_index: Mapped[int] = mapped_column(Integer, nullable=False)
    block_type: Mapped[str] = mapped_column(String(64), nullable=False, default="text")
    text: Mapped[str | None] = mapped_column(Text)
    text_hash: Mapped[str | None] = mapped_column(String(128))
    x0_points: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    y0_points: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    x1_points: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    y1_points: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="pdf_blocks")
    page: Mapped[PdfPage] = relationship(back_populates="blocks")


class SourceArtifact(Base, TimestampMixin):
    __tablename__ = "source_artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"),
        nullable=False,
    )
    kind: Mapped[ArtifactKind] = mapped_column(Enum(ArtifactKind, name="artifact_kind"))
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    byte_size: Mapped[int | None] = mapped_column(Integer)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="artifacts")


class DocumentChunk(Base, TimestampMixin):
    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("section_id", "chunk_index", name="uq_chunk_section_index"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("document_versions.id"),
        nullable=False,
    )
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("filing_sections.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)

    document_version: Mapped[DocumentVersion] = relationship(back_populates="chunks")
    section: Mapped[FilingSection] = relationship(back_populates="chunks")
    embeddings: Mapped[list[ChunkEmbedding]] = relationship(
        back_populates="chunk",
        cascade="all, delete-orphan",
    )


class EmbeddingIndex(Base, TimestampMixin):
    __tablename__ = "embedding_indexes"
    __table_args__ = (UniqueConstraint("name", "index_version", name="uq_embedding_index_version"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    index_version: Mapped[str] = mapped_column(String(64), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_metric: Mapped[str] = mapped_column(String(32), nullable=False, default="cosine")
    metadata_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)

    embeddings: Mapped[list[ChunkEmbedding]] = relationship(back_populates="embedding_index")


class ChunkEmbedding(Base, TimestampMixin):
    __tablename__ = "chunk_embeddings"
    __table_args__ = (
        UniqueConstraint("chunk_id", "embedding_index_id", name="uq_chunk_embedding_index"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    chunk_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document_chunks.id"), nullable=False)
    embedding_index_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("embedding_indexes.id"),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(PgVector(384), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    chunk: Mapped[DocumentChunk] = relationship(back_populates="embeddings")
    embedding_index: Mapped[EmbeddingIndex] = relationship(back_populates="embeddings")


class FinancialFact(Base, TimestampMixin):
    __tablename__ = "financial_facts"
    __table_args__ = (UniqueConstraint("source_hash", name="uq_financial_fact_source_hash"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    company_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("companies.id"), nullable=False)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id")
    )
    taxonomy: Mapped[str] = mapped_column(String(64), nullable=False)
    concept: Mapped[str] = mapped_column(String(255), nullable=False)
    canonical_metric: Mapped[str] = mapped_column(String(64), nullable=False, default="legacy")
    metric_mapping_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="legacy"
    )
    label: Mapped[str | None] = mapped_column(String(512))
    value: Mapped[Decimal] = mapped_column(Numeric(28, 6), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(16))
    period_type: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    form: Mapped[str | None] = mapped_column(String(32))
    filed_date: Mapped[date | None] = mapped_column(Date)
    frame: Mapped[str | None] = mapped_column(String(64))
    is_amendment: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    accession_number: Mapped[str | None] = mapped_column(String(64))
    dimensions: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    company: Mapped[Company] = relationship(back_populates="facts")
    ingestion_run: Mapped[IngestionRun | None] = relationship()
    document_version: Mapped[DocumentVersion | None] = relationship()


class MacroSeries(Base, TimestampMixin):
    __tablename__ = "macro_series"

    series_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    frequency: Mapped[str] = mapped_column(String(128), nullable=False)
    frequency_short: Mapped[str] = mapped_column(String(32), nullable=False)
    units: Mapped[str] = mapped_column(String(128), nullable=False)
    units_short: Mapped[str] = mapped_column(String(64), nullable=False)
    seasonal_adjustment: Mapped[str] = mapped_column(String(255), nullable=False)
    seasonal_adjustment_short: Mapped[str] = mapped_column(String(64), nullable=False)
    observation_start: Mapped[date] = mapped_column(Date, nullable=False)
    observation_end: Mapped[date] = mapped_column(Date, nullable=False)
    last_updated_at_source: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)

    observations: Mapped[list[MacroObservation]] = relationship(
        back_populates="series",
        cascade="all, delete-orphan",
    )


class MacroObservation(Base, TimestampMixin):
    __tablename__ = "macro_observations"
    __table_args__ = (
        UniqueConstraint(
            "series_id",
            "observed_at",
            "realtime_start",
            "realtime_end",
            name="uq_macro_observation_vintage",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ingestion_run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ingestion_runs.id"))
    series_id: Mapped[str] = mapped_column(ForeignKey("macro_series.series_id"), nullable=False)
    source_name: Mapped[str] = mapped_column(String(128), nullable=False)
    observed_at: Mapped[date] = mapped_column(Date, nullable=False)
    vintage_date: Mapped[date | None] = mapped_column(Date)
    realtime_start: Mapped[date] = mapped_column(Date, nullable=False)
    realtime_end: Mapped[date] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(38, 12))
    raw_value: Mapped[str] = mapped_column(String(128), nullable=False)
    is_missing: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    frequency: Mapped[str] = mapped_column(String(32), nullable=False)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(128), nullable=False)

    ingestion_run: Mapped[IngestionRun | None] = relationship(back_populates="macro_observations")
    series: Mapped[MacroSeries] = relationship(back_populates="observations")


class EvidenceRecord(Base, TimestampMixin):
    __tablename__ = "evidence_records"
    __table_args__ = (UniqueConstraint("stable_id", name="uq_evidence_record_stable_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    stable_id: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[EvidenceKind] = mapped_column(Enum(EvidenceKind, name="evidence_kind"))
    document_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document_versions.id")
    )
    section_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("filing_sections.id"))
    chunk_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("document_chunks.id"))
    page_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("pdf_pages.id"))
    financial_fact_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("financial_facts.id"))
    macro_observation_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("macro_observations.id")
    )
    quote_text: Mapped[str | None] = mapped_column(Text)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)
    lineage_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)

    document_version: Mapped[DocumentVersion | None] = relationship()
    section: Mapped[FilingSection | None] = relationship()
    chunk: Mapped[DocumentChunk | None] = relationship()
    page: Mapped[PdfPage | None] = relationship()
    financial_fact: Mapped[FinancialFact | None] = relationship()
    macro_observation: Mapped[MacroObservation | None] = relationship()
    citations: Mapped[list[CitationRecord]] = relationship(
        back_populates="evidence",
        cascade="all, delete-orphan",
    )


class ClaimRecord(Base, TimestampMixin):
    __tablename__ = "claim_records"
    __table_args__ = (UniqueConstraint("run_id", "claim_key", name="uq_claim_run_key"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    claim_key: Mapped[str] = mapped_column(String(255), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    material: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    validation_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)

    citations: Mapped[list[CitationRecord]] = relationship(back_populates="claim")


class CitationRecord(Base, TimestampMixin):
    __tablename__ = "citation_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    evidence_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("evidence_records.id"), nullable=False
    )
    claim_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("claim_records.id"))
    claim_key: Mapped[str | None] = mapped_column(String(255))
    citation_label: Mapped[str] = mapped_column(String(64), nullable=False)
    display_text: Mapped[str] = mapped_column(String(512), nullable=False)
    metadata_json: Mapped[JsonObject] = mapped_column(JSON_TYPE, nullable=False, default=dict)

    evidence: Mapped[EvidenceRecord] = relationship(back_populates="citations")
    claim: Mapped[ClaimRecord | None] = relationship(back_populates="citations")
