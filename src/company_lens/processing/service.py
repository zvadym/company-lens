from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from company_lens.db.models import (
    ChunkEmbedding,
    DocumentChunk,
    DocumentKind,
    DocumentSummary,
    DocumentVersion,
    FilingSection,
    PdfPage,
    SectionSummary,
    SourceDocument,
)
from company_lens.processing.text import (
    TextSpan,
    content_hash,
    decode_document_content,
    estimate_token_count,
    fixed_token_chunks,
    looks_like_boilerplate,
    prompt_hash,
    semantic_chunks,
    shingle_fingerprint,
    summarize_text,
)
from company_lens.prompts import repo_text_prompt

ChunkingStrategy = Literal["fixed-token", "semantic"]

DEFAULT_CHUNKING_VERSION = "chunking.cl100k.v2"
DEFAULT_SUMMARY_PROMPT_VERSION = "summary.extractive.v1"
DEFAULT_SUMMARY_MODEL = "local-extractive-v1"
PROCESSING_SOURCE_NAME = "document_processing"

DOCUMENT_SUMMARY_PROMPT = repo_text_prompt("processing/document-summary")
SECTION_SUMMARY_PROMPT = repo_text_prompt("processing/section-summary")


@dataclass(frozen=True)
class DocumentProcessingOptions:
    document_version_ids: tuple[uuid.UUID, ...] = ()
    current_only: bool = True
    document_kinds: tuple[DocumentKind, ...] = (DocumentKind.SEC_FILING, DocumentKind.INVESTOR_PDF)
    limit: int | None = None
    chunking_strategy: ChunkingStrategy = "fixed-token"
    max_tokens: int = 320
    overlap_tokens: int = 40
    duplicate_threshold: float = 0.9
    chunking_version: str = DEFAULT_CHUNKING_VERSION
    summary_prompt_version: str = DEFAULT_SUMMARY_PROMPT_VERSION
    summary_model_name: str = DEFAULT_SUMMARY_MODEL
    force: bool = False


@dataclass(frozen=True)
class ProcessedDocumentStats:
    document_version_id: str
    source_document_id: str
    title: str | None
    kind: str
    status: str
    sections_seen: int
    summaries_written: int
    chunks_written: int
    duplicate_chunks_removed: int
    boilerplate_chunks_removed: int
    duplicate_chunk_rate: float
    boilerplate_chunk_rate: float
    token_count: int


@dataclass(frozen=True)
class DocumentProcessingResult:
    status: str
    documents_seen: int
    documents_processed: int
    documents_skipped: int
    sections_seen: int
    summaries_written: int
    chunks_written: int
    duplicate_chunks_removed: int
    boilerplate_chunks_removed: int
    duplicate_chunk_rate: float
    boilerplate_chunk_rate: float
    token_count: int
    documents: tuple[ProcessedDocumentStats, ...]


@dataclass(frozen=True)
class _SectionInput:
    section: FilingSection
    text: str
    char_start: int | None
    char_end: int | None
    page_start: int | None
    page_end: int | None


@dataclass(frozen=True)
class _ChunkCandidate:
    section: FilingSection
    span: TextSpan


class _FingerprintIndex:
    def __init__(self) -> None:
        self._fingerprints: list[frozenset[str]] = []
        self._postings: defaultdict[str, list[int]] = defaultdict(list)
        self._empty_count = 0

    def contains_near_duplicate(
        self,
        fingerprint: frozenset[str],
        threshold: float,
    ) -> bool:
        if not self._fingerprints:
            return False
        if threshold <= 0:
            return True
        if not fingerprint:
            return self._empty_count > 0

        intersections: Counter[int] = Counter()
        for shingle in fingerprint:
            intersections.update(self._postings[shingle])
        for index, intersection_size in intersections.items():
            accepted = self._fingerprints[index]
            union_size = len(fingerprint) + len(accepted) - intersection_size
            if union_size and intersection_size / union_size >= threshold:
                return True
        return False

    def add(self, fingerprint: frozenset[str]) -> None:
        index = len(self._fingerprints)
        self._fingerprints.append(fingerprint)
        if not fingerprint:
            self._empty_count += 1
            return
        for shingle in fingerprint:
            self._postings[shingle].append(index)


class DocumentProcessingService:
    def __init__(self, *, session: Session) -> None:
        self._session = session

    def process(self, options: DocumentProcessingOptions) -> DocumentProcessingResult:
        document_versions = self._find_document_versions(options)
        stats: list[ProcessedDocumentStats] = []
        for document_version in document_versions:
            stats.append(self._process_document_version(document_version, options))

        chunks_written = sum(item.chunks_written for item in stats)
        duplicate_chunks_removed = sum(item.duplicate_chunks_removed for item in stats)
        boilerplate_chunks_removed = sum(item.boilerplate_chunks_removed for item in stats)
        return DocumentProcessingResult(
            status="success",
            documents_seen=len(document_versions),
            documents_processed=sum(1 for item in stats if item.status == "processed"),
            documents_skipped=sum(1 for item in stats if item.status == "skipped"),
            sections_seen=sum(item.sections_seen for item in stats),
            summaries_written=sum(item.summaries_written for item in stats),
            chunks_written=chunks_written,
            duplicate_chunks_removed=duplicate_chunks_removed,
            boilerplate_chunks_removed=boilerplate_chunks_removed,
            duplicate_chunk_rate=_rate(
                duplicate_chunks_removed,
                chunks_written + duplicate_chunks_removed + boilerplate_chunks_removed,
            ),
            boilerplate_chunk_rate=_rate(
                boilerplate_chunks_removed,
                chunks_written + duplicate_chunks_removed + boilerplate_chunks_removed,
            ),
            token_count=sum(item.token_count for item in stats),
            documents=tuple(stats),
        )

    def _find_document_versions(self, options: DocumentProcessingOptions) -> list[DocumentVersion]:
        if options.document_version_ids:
            statement = (
                select(DocumentVersion)
                .where(DocumentVersion.id.in_(options.document_version_ids))
                .order_by(DocumentVersion.created_at)
            )
        else:
            statement = (
                select(DocumentVersion)
                .join(SourceDocument, SourceDocument.id == DocumentVersion.document_id)
                .where(SourceDocument.kind.in_(options.document_kinds))
                .order_by(SourceDocument.filing_date.desc(), SourceDocument.created_at.desc())
            )
            if options.current_only:
                statement = statement.where(DocumentVersion.is_current.is_(True))
            if options.limit is not None:
                statement = statement.limit(options.limit)
        return list(self._session.scalars(statement).all())

    def _process_document_version(
        self,
        document_version: DocumentVersion,
        options: DocumentProcessingOptions,
    ) -> ProcessedDocumentStats:
        document = self._session.get(SourceDocument, document_version.document_id)
        if document is None:
            raise ValueError(f"Document version {document_version.id} has no source document.")

        processing_hash = _processing_hash(document_version, options)
        if _already_processed(document_version, processing_hash) and not options.force:
            return ProcessedDocumentStats(
                document_version_id=str(document_version.id),
                source_document_id=str(document.id),
                title=document.title,
                kind=document.kind.value,
                status="skipped",
                sections_seen=0,
                summaries_written=0,
                chunks_written=0,
                duplicate_chunks_removed=0,
                boilerplate_chunks_removed=0,
                duplicate_chunk_rate=0.0,
                boilerplate_chunk_rate=0.0,
                token_count=0,
            )

        section_inputs = self._build_section_inputs(document_version, document)
        self._clear_previous_outputs(document_version, section_inputs)

        summaries_written = self._write_summaries(document_version, section_inputs, options)
        candidates = list(self._build_chunk_candidates(section_inputs, options))
        chunks_written, duplicate_count, boilerplate_count, token_count = self._write_chunks(
            document_version,
            candidates,
            options,
        )
        candidate_count = chunks_written + duplicate_count + boilerplate_count

        document_version.metadata_json = {
            **document_version.metadata_json,
            "last_processing": {
                "source": PROCESSING_SOURCE_NAME,
                "processing_hash": processing_hash,
                "processed_at": datetime.now(UTC).isoformat(),
                "chunking_strategy": options.chunking_strategy,
                "chunking_version": options.chunking_version,
                "summary_prompt_version": options.summary_prompt_version,
                "summary_model_name": options.summary_model_name,
                "max_tokens": options.max_tokens,
                "overlap_tokens": options.overlap_tokens,
                "sections_seen": len(section_inputs),
                "summaries_written": summaries_written,
                "chunks_written": chunks_written,
                "candidate_chunks_seen": candidate_count,
                "duplicate_chunks_removed": duplicate_count,
                "boilerplate_chunks_removed": boilerplate_count,
                "duplicate_chunk_rate": _rate(duplicate_count, candidate_count),
                "boilerplate_chunk_rate": _rate(boilerplate_count, candidate_count),
                "token_count": token_count,
            },
        }
        self._session.commit()

        return ProcessedDocumentStats(
            document_version_id=str(document_version.id),
            source_document_id=str(document.id),
            title=document.title,
            kind=document.kind.value,
            status="processed",
            sections_seen=len(section_inputs),
            summaries_written=summaries_written,
            chunks_written=chunks_written,
            duplicate_chunks_removed=duplicate_count,
            boilerplate_chunks_removed=boilerplate_count,
            duplicate_chunk_rate=_rate(duplicate_count, candidate_count),
            boilerplate_chunk_rate=_rate(boilerplate_count, candidate_count),
            token_count=token_count,
        )

    def _build_section_inputs(
        self,
        document_version: DocumentVersion,
        document: SourceDocument,
    ) -> list[_SectionInput]:
        if document.kind == DocumentKind.INVESTOR_PDF:
            return self._build_pdf_section_inputs(document_version, document)
        return self._build_text_section_inputs(document_version, document)

    def _build_text_section_inputs(
        self,
        document_version: DocumentVersion,
        document: SourceDocument,
    ) -> list[_SectionInput]:
        text = self._document_text(document_version)
        sections = list(
            self._session.scalars(
                select(FilingSection)
                .where(FilingSection.document_version_id == document_version.id)
                .order_by(FilingSection.ordinal_path)
            ).all()
        )
        if not sections:
            sections = [self._upsert_root_section(document_version, document, text)]

        inputs: list[_SectionInput] = []
        for section in sections:
            start = section.char_start if section.char_start is not None else 0
            end = section.char_end if section.char_end is not None else len(text)
            bounded_start = max(0, min(start, len(text)))
            bounded_end = max(bounded_start, min(end, len(text)))
            section_text = text[bounded_start:bounded_end].strip()
            if not section_text:
                continue
            inputs.append(
                _SectionInput(
                    section=section,
                    text=section_text,
                    char_start=bounded_start,
                    char_end=bounded_end,
                    page_start=section.page_start,
                    page_end=section.page_end,
                )
            )
        return inputs

    def _build_pdf_section_inputs(
        self,
        document_version: DocumentVersion,
        document: SourceDocument,
    ) -> list[_SectionInput]:
        pages = list(
            self._session.scalars(
                select(PdfPage)
                .where(PdfPage.document_version_id == document_version.id)
                .order_by(PdfPage.page_number)
            ).all()
        )
        page_texts = [
            (page.page_number, page.text or "") for page in pages if (page.text or "").strip()
        ]
        document_text = "\n\n".join(text for _, text in page_texts)
        if not document_text.strip():
            return []

        page_start = page_texts[0][0] if page_texts else None
        page_end = page_texts[-1][0] if page_texts else None
        section = self._upsert_pdf_root_section(
            document_version,
            document,
            document_text,
            page_start=page_start,
            page_end=page_end,
        )
        return [
            _SectionInput(
                section=section,
                text=document_text,
                char_start=0,
                char_end=len(document_text),
                page_start=page_start,
                page_end=page_end,
            )
        ]

    def _document_text(self, document_version: DocumentVersion) -> str:
        if document_version.artifact_uri is None:
            raise ValueError(f"Document version {document_version.id} has no artifact URI.")
        path = Path(document_version.artifact_uri)
        content_type = _optional_str(document_version.metadata_json.get("mime_type"))
        return decode_document_content(path.read_bytes(), content_type=content_type)

    def _upsert_root_section(
        self,
        document_version: DocumentVersion,
        document: SourceDocument,
        text: str,
    ) -> FilingSection:
        return self._upsert_generated_section(
            document_version=document_version,
            title=document.title or "Document",
            ordinal_path="document",
            section_code="document",
            text=text,
            char_start=0,
            char_end=len(text),
            page_start=None,
            page_end=None,
        )

    def _upsert_pdf_root_section(
        self,
        document_version: DocumentVersion,
        document: SourceDocument,
        text: str,
        *,
        page_start: int | None,
        page_end: int | None,
    ) -> FilingSection:
        return self._upsert_generated_section(
            document_version=document_version,
            title=document.title or "Investor PDF",
            ordinal_path="pdf.document",
            section_code="pdf_document",
            text=text,
            char_start=0,
            char_end=len(text),
            page_start=page_start,
            page_end=page_end,
        )

    def _upsert_generated_section(
        self,
        *,
        document_version: DocumentVersion,
        title: str,
        ordinal_path: str,
        section_code: str,
        text: str,
        char_start: int,
        char_end: int,
        page_start: int | None,
        page_end: int | None,
    ) -> FilingSection:
        section = self._session.scalar(
            select(FilingSection).where(
                FilingSection.document_version_id == document_version.id,
                FilingSection.ordinal_path == ordinal_path,
            )
        )
        if section is None:
            section = FilingSection(
                document_version_id=document_version.id,
                title=title,
                ordinal_path=ordinal_path,
                section_code=section_code,
                heading_level=1,
                source_section_id=ordinal_path,
                content_hash=content_hash(text),
            )
            self._session.add(section)
        section.title = title
        section.section_code = section_code
        section.source_section_id = ordinal_path
        section.char_start = char_start
        section.char_end = char_end
        section.page_start = page_start
        section.page_end = page_end
        section.content_hash = content_hash(text)
        self._session.flush()
        return section

    def _clear_previous_outputs(
        self,
        document_version: DocumentVersion,
        section_inputs: Iterable[_SectionInput],
    ) -> None:
        self._session.execute(
            delete(ChunkEmbedding).where(
                ChunkEmbedding.chunk_id.in_(
                    select(DocumentChunk.id).where(
                        DocumentChunk.document_version_id == document_version.id
                    )
                )
            )
        )
        self._session.execute(
            delete(DocumentChunk).where(DocumentChunk.document_version_id == document_version.id)
        )
        self._session.execute(
            delete(DocumentSummary).where(
                DocumentSummary.document_version_id == document_version.id
            )
        )
        section_ids = [section_input.section.id for section_input in section_inputs]
        if section_ids:
            self._session.execute(
                delete(SectionSummary).where(SectionSummary.section_id.in_(section_ids))
            )
        self._session.flush()

    def _write_summaries(
        self,
        document_version: DocumentVersion,
        section_inputs: list[_SectionInput],
        options: DocumentProcessingOptions,
    ) -> int:
        document_text = "\n\n".join(section_input.text for section_input in section_inputs)
        if not document_text.strip():
            return 0

        written = 0
        document_summary = summarize_text(document_text, max_sentences=5, max_chars=1200)
        self._session.add(
            DocumentSummary(
                document_version_id=document_version.id,
                summary_text=document_summary,
                model_name=options.summary_model_name,
                prompt_hash=prompt_hash(DOCUMENT_SUMMARY_PROMPT),
                content_hash=content_hash(document_summary),
                metadata_json={
                    "prompt_version": options.summary_prompt_version,
                    "summary_kind": "document",
                    "source": PROCESSING_SOURCE_NAME,
                },
            )
        )
        written += 1

        for section_input in section_inputs:
            summary = summarize_text(section_input.text, max_sentences=3, max_chars=700)
            self._session.add(
                SectionSummary(
                    section_id=section_input.section.id,
                    summary_text=summary,
                    model_name=options.summary_model_name,
                    prompt_hash=prompt_hash(SECTION_SUMMARY_PROMPT),
                    content_hash=content_hash(summary),
                    metadata_json={
                        "prompt_version": options.summary_prompt_version,
                        "summary_kind": "section",
                        "source": PROCESSING_SOURCE_NAME,
                    },
                )
            )
            written += 1
        return written

    def _build_chunk_candidates(
        self,
        section_inputs: list[_SectionInput],
        options: DocumentProcessingOptions,
    ) -> Iterable[_ChunkCandidate]:
        for section_input in section_inputs:
            if options.chunking_strategy == "semantic":
                spans = semantic_chunks(
                    section_input.text,
                    max_tokens=options.max_tokens,
                    overlap_tokens=options.overlap_tokens,
                    base_char_start=section_input.char_start or 0,
                    page_start=section_input.page_start,
                    page_end=section_input.page_end,
                )
            else:
                spans = fixed_token_chunks(
                    section_input.text,
                    max_tokens=options.max_tokens,
                    overlap_tokens=options.overlap_tokens,
                    base_char_start=section_input.char_start or 0,
                    page_start=section_input.page_start,
                    page_end=section_input.page_end,
                )
            for span in spans:
                yield _ChunkCandidate(section=section_input.section, span=span)

    def _write_chunks(
        self,
        document_version: DocumentVersion,
        candidates: list[_ChunkCandidate],
        options: DocumentProcessingOptions,
    ) -> tuple[int, int, int, int]:
        fingerprint_index = _FingerprintIndex()
        section_indexes: dict[uuid.UUID, int] = {}
        chunks_written = 0
        duplicate_count = 0
        boilerplate_count = 0
        token_count = 0

        for candidate in candidates:
            if looks_like_boilerplate(candidate.span.text):
                boilerplate_count += 1
                continue

            fingerprint = shingle_fingerprint(candidate.span.text)
            if fingerprint_index.contains_near_duplicate(
                fingerprint,
                options.duplicate_threshold,
            ):
                duplicate_count += 1
                continue
            fingerprint_index.add(fingerprint)

            chunk_index = section_indexes.get(candidate.section.id, 0)
            section_indexes[candidate.section.id] = chunk_index + 1
            estimated_tokens = estimate_token_count(candidate.span.text)
            token_count += estimated_tokens
            self._session.add(
                DocumentChunk(
                    document_version_id=document_version.id,
                    section_id=candidate.section.id,
                    chunk_index=chunk_index,
                    text=candidate.span.text,
                    content_hash=content_hash(candidate.span.text),
                    token_count=estimated_tokens,
                    char_start=candidate.span.char_start,
                    char_end=candidate.span.char_end,
                    page_start=candidate.span.page_start,
                    page_end=candidate.span.page_end,
                    metadata_json={
                        "chunking_strategy": options.chunking_strategy,
                        "chunking_version": options.chunking_version,
                        "max_tokens": options.max_tokens,
                        "overlap_tokens": options.overlap_tokens,
                        "source": PROCESSING_SOURCE_NAME,
                    },
                )
            )
            chunks_written += 1

        return chunks_written, duplicate_count, boilerplate_count, token_count


def _processing_hash(
    document_version: DocumentVersion,
    options: DocumentProcessingOptions,
) -> str:
    payload = "|".join(
        (
            document_version.content_hash,
            options.chunking_strategy,
            options.chunking_version,
            options.summary_prompt_version,
            options.summary_model_name,
            str(options.max_tokens),
            str(options.overlap_tokens),
            str(options.duplicate_threshold),
        )
    )
    return content_hash(payload)


def _already_processed(document_version: DocumentVersion, processing_hash: str) -> bool:
    metadata = document_version.metadata_json.get("last_processing")
    if not isinstance(metadata, dict):
        return False
    return metadata.get("processing_hash") == processing_hash


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)
