from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from company_lens.db.models import (
    Company,
    DocumentChunk,
    DocumentKind,
    DocumentSummary,
    DocumentVersion,
    FilingSection,
    PdfBlock,
    PdfPage,
    SectionSummary,
    SourceDocument,
)


def corpus_stats(session: Session) -> dict[str, Any]:
    chunk_token_count = session.scalar(
        select(func.coalesce(func.sum(DocumentChunk.token_count), 0))
    )
    last_processing_rows = session.scalars(select(DocumentVersion)).all()

    duplicate_removed = 0
    boilerplate_removed = 0
    for document_version in last_processing_rows:
        metadata = document_version.metadata_json.get("last_processing")
        if not isinstance(metadata, dict):
            continue
        duplicate_removed += int(metadata.get("duplicate_chunks_removed") or 0)
        boilerplate_removed += int(metadata.get("boilerplate_chunks_removed") or 0)
    persisted_chunks = _count(session, DocumentChunk)
    candidate_chunks = persisted_chunks + duplicate_removed + boilerplate_removed

    return {
        "companies": _count(session, Company),
        "source_documents": _count(session, SourceDocument),
        "document_versions": _count(session, DocumentVersion),
        "document_summaries": _count(session, DocumentSummary),
        "filing_sections": _count(session, FilingSection),
        "section_summaries": _count(session, SectionSummary),
        "document_chunks": persisted_chunks,
        "chunk_tokens": int(chunk_token_count or 0),
        "pdf_pages": _count(session, PdfPage),
        "pdf_blocks": _count(session, PdfBlock),
        "duplicate_chunks_removed": duplicate_removed,
        "boilerplate_chunks_removed": boilerplate_removed,
        "duplicate_chunk_rate": _rate(duplicate_removed, candidate_chunks),
        "boilerplate_chunk_rate": _rate(boilerplate_removed, candidate_chunks),
        "documents_by_kind": _documents_by_kind(session),
    }


def demo_chunks(session: Session, *, limit: int = 5) -> list[dict[str, Any]]:
    rows = session.execute(
        select(SourceDocument, DocumentVersion, FilingSection, DocumentChunk)
        .join(DocumentVersion, DocumentVersion.document_id == SourceDocument.id)
        .join(FilingSection, FilingSection.document_version_id == DocumentVersion.id)
        .join(DocumentChunk, DocumentChunk.section_id == FilingSection.id)
        .order_by(
            SourceDocument.created_at.desc(),
            FilingSection.ordinal_path,
            DocumentChunk.chunk_index,
        )
        .limit(limit)
    ).all()
    return [
        {
            "company_document": document.title,
            "kind": document.kind.value,
            "section": section.title,
            "chunk_index": chunk.chunk_index,
            "token_count": chunk.token_count,
            "page_start": chunk.page_start,
            "page_end": chunk.page_end,
            "source_url": document.source_url,
            "text": _preview(chunk.text),
        }
        for document, _version, section, chunk in rows
    ]


def _count(session: Session, model: type[object]) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _documents_by_kind(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(SourceDocument.kind, func.count(SourceDocument.id)).group_by(SourceDocument.kind)
    ).all()
    return {
        (kind.value if isinstance(kind, DocumentKind) else str(kind)): int(count)
        for kind, count in rows
    }


def _preview(text: str, *, max_chars: int = 360) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rsplit(" ", 1)[0] + "..."


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
