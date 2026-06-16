from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import sleep
from typing import Any

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from company_lens.config import Settings
from company_lens.db.models import (
    ArtifactKind,
    Company,
    CompanyIdentifier,
    DocumentKind,
    DocumentVersion,
    DocumentVersionState,
    IdentifierKind,
    IngestionFailure,
    IngestionRun,
    IngestionRunStatus,
    PdfBlock,
    PdfPage,
    SourceArtifact,
    SourceDocument,
)
from company_lens.ingestion.artifacts import ArtifactStore, StoredArtifact
from company_lens.ingestion.pdf_manifest import InvestorPdfManifestDocument
from company_lens.ingestion.pdf_parser import ParsedPdf, PdfParseError, PdfParser

INVESTOR_PDF_SOURCE_SYSTEM = "investor_relations_pdf"


class InvestorPdfClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class InvestorPdfIngestionOptions:
    documents: tuple[InvestorPdfManifestDocument, ...]


@dataclass(frozen=True)
class InvestorPdfIngestionResult:
    run_id: str
    status: str
    documents_seen: int
    pages_seen: int
    blocks_seen: int
    artifacts_seen: int
    failures: int


class InvestorPdfClient:
    def __init__(
        self,
        *,
        user_agent: str,
        timeout_seconds: float = 30.0,
        retry_attempts: int = 3,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._retry_attempts = max(1, retry_attempts)
        self._client = httpx.Client(
            headers={
                "User-Agent": user_agent,
                "Accept": "application/pdf,*/*",
            },
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> InvestorPdfClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def get_bytes(self, url: str) -> tuple[bytes, str | None]:
        last_error: Exception | None = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                response = self._client.get(url)
                response.raise_for_status()
                return response.content, response.headers.get("content-type")
            except (httpx.HTTPStatusError, httpx.RequestError) as exc:
                last_error = exc
                if attempt == self._retry_attempts:
                    break
                sleep(min(2.0, 0.25 * attempt))
        raise InvestorPdfClientError(f"PDF request failed for {url}: {last_error!r}")


class InvestorPdfIngestionService:
    def __init__(
        self,
        *,
        session: Session,
        client: InvestorPdfClient,
        artifact_store: ArtifactStore,
        parser: PdfParser | None = None,
    ) -> None:
        self._session = session
        self._client = client
        self._artifact_store = artifact_store
        self._parser = parser or PdfParser()

    def ingest(self, options: InvestorPdfIngestionOptions) -> InvestorPdfIngestionResult:
        run = IngestionRun(
            source_name=INVESTOR_PDF_SOURCE_SYSTEM,
            status=IngestionRunStatus.STARTED,
            parameters={
                "document_count": len(options.documents),
                "document_ids": [_stable_source_id(document) for document in options.documents],
            },
        )
        self._session.add(run)
        self._session.commit()

        documents_seen = 0
        pages_seen = 0
        blocks_seen = 0
        artifacts_seen = 0

        for manifest_document in options.documents:
            document: SourceDocument | None = None
            company: Company | None = None
            try:
                company = self._upsert_company(manifest_document)
                document = self._upsert_source_document(company, manifest_document)
                content, mime_type = self._client.get_bytes(manifest_document.source_url)
                stored = self._store_raw_pdf(manifest_document, content, mime_type)
                document_version = self._upsert_document_version(
                    run=run,
                    document=document,
                    stored=stored,
                    manifest_document=manifest_document,
                )
                self._upsert_artifact(
                    document_version=document_version,
                    source_url=manifest_document.source_url,
                    stored=stored,
                )
                artifacts_seen += 1

                parsed = self._parser.parse(content)
                page_count, block_count = self._upsert_pages_and_blocks(document_version, parsed)
                pages_seen += page_count
                blocks_seen += block_count
                documents_seen += 1
                self._mark_failures_resolved(company_id=company.id, source_document_id=document.id)
                self._record_parse_diagnostics(
                    run=run,
                    company=company,
                    document=document,
                    document_version=document_version,
                    parsed=parsed,
                )
            except Exception as exc:
                self._record_failure(
                    run=run,
                    stage=_stage_for_exception(exc),
                    message=str(exc),
                    company_id=company.id if company is not None else None,
                    source_document_id=document.id if document is not None else None,
                    retryable=not isinstance(exc, PdfParseError),
                    details={
                        "title": manifest_document.title,
                        "source_url": manifest_document.source_url,
                        "stable_source_id": _stable_source_id(manifest_document),
                    },
                )

        failure_count = self._count_failures(run.id)
        run.status = (
            IngestionRunStatus.SUCCEEDED if failure_count == 0 else IngestionRunStatus.PARTIAL
        )
        run.completed_at = datetime.now(UTC)
        run.parameters = {
            **run.parameters,
            "documents_seen": documents_seen,
            "pages_seen": pages_seen,
            "blocks_seen": blocks_seen,
            "artifacts_seen": artifacts_seen,
            "failures": failure_count,
        }
        self._session.commit()

        return InvestorPdfIngestionResult(
            run_id=str(run.id),
            status="success" if failure_count == 0 else "partial_failed",
            documents_seen=documents_seen,
            pages_seen=pages_seen,
            blocks_seen=blocks_seen,
            artifacts_seen=artifacts_seen,
            failures=failure_count,
        )

    def _upsert_company(self, manifest_document: InvestorPdfManifestDocument) -> Company:
        company: Company | None = None
        if manifest_document.cik is not None:
            company = self._session.scalar(
                select(Company).where(Company.cik == manifest_document.cik)
            )
        if company is None:
            company = self._session.scalar(
                select(Company).where(Company.display_name == manifest_document.company_name)
            )

        if company is None:
            company = Company(
                legal_name=manifest_document.company_name,
                display_name=manifest_document.company_name,
                cik=manifest_document.cik,
            )
            self._session.add(company)
        else:
            company.legal_name = manifest_document.company_name
            company.display_name = manifest_document.company_name
            company.cik = manifest_document.cik or company.cik
        self._session.flush()

        if manifest_document.cik is not None:
            self._upsert_cik_identifier(company, manifest_document.cik)
        self._session.commit()
        return company

    def _upsert_cik_identifier(self, company: Company, cik: str) -> None:
        identifier = self._session.scalar(
            select(CompanyIdentifier).where(
                CompanyIdentifier.kind == IdentifierKind.CIK,
                CompanyIdentifier.value == cik,
            )
        )
        if identifier is None:
            self._session.add(
                CompanyIdentifier(
                    company_id=company.id,
                    kind=IdentifierKind.CIK,
                    value=cik,
                    source=INVESTOR_PDF_SOURCE_SYSTEM,
                )
            )
        else:
            identifier.company_id = company.id
            identifier.source = INVESTOR_PDF_SOURCE_SYSTEM

    def _upsert_source_document(
        self,
        company: Company,
        manifest_document: InvestorPdfManifestDocument,
    ) -> SourceDocument:
        stable_source_id = _stable_source_id(manifest_document)
        document = self._session.scalar(
            select(SourceDocument).where(
                SourceDocument.source_system == INVESTOR_PDF_SOURCE_SYSTEM,
                SourceDocument.stable_source_id == stable_source_id,
            )
        )
        metadata = {
            **(manifest_document.metadata or {}),
            "document_type": manifest_document.document_type,
            "manifest_id": manifest_document.manifest_id,
            "ticker": manifest_document.ticker,
            "cik": manifest_document.cik,
        }
        if document is None:
            document = SourceDocument(
                company_id=company.id,
                kind=DocumentKind.INVESTOR_PDF,
                source_system=INVESTOR_PDF_SOURCE_SYSTEM,
                stable_source_id=stable_source_id,
                source_url=manifest_document.source_url,
                title=manifest_document.title,
                period_end=manifest_document.period_end,
                fiscal_year=manifest_document.fiscal_year,
                fiscal_period=manifest_document.fiscal_period,
                metadata_json=metadata,
            )
            self._session.add(document)
        else:
            document.company_id = company.id
            document.kind = DocumentKind.INVESTOR_PDF
            document.source_url = manifest_document.source_url
            document.title = manifest_document.title
            document.period_end = manifest_document.period_end
            document.fiscal_year = manifest_document.fiscal_year
            document.fiscal_period = manifest_document.fiscal_period
            document.metadata_json = metadata
        self._session.commit()
        return document

    def _store_raw_pdf(
        self,
        manifest_document: InvestorPdfManifestDocument,
        content: bytes,
        mime_type: str | None,
    ) -> StoredArtifact:
        relative_path = (
            Path(_company_path_segment(manifest_document))
            / f"{_safe_path_segment(_stable_source_id(manifest_document))}.pdf"
        )
        return self._artifact_store.store_bytes(
            relative_path=relative_path,
            content=content,
            mime_type=mime_type or "application/pdf",
        )

    def _upsert_document_version(
        self,
        *,
        run: IngestionRun,
        document: SourceDocument,
        stored: StoredArtifact,
        manifest_document: InvestorPdfManifestDocument,
    ) -> DocumentVersion:
        document_version = self._session.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == document.id,
                DocumentVersion.content_hash == stored.content_hash,
            )
        )
        if document_version is None:
            current_versions = self._session.scalars(
                select(DocumentVersion).where(
                    DocumentVersion.document_id == document.id,
                    DocumentVersion.is_current.is_(True),
                )
            )
            for version in current_versions:
                version.is_current = False
            document_version = DocumentVersion(
                document_id=document.id,
                ingestion_run_id=run.id,
                version_label=manifest_document.manifest_id or stored.content_hash[:12],
                content_hash=stored.content_hash,
                source_hash=stored.content_hash,
                artifact_uri=str(stored.path),
                state=DocumentVersionState.CURRENT,
                is_current=True,
                metadata_json={
                    "byte_size": stored.size_bytes,
                    "mime_type": stored.mime_type,
                    "document_type": manifest_document.document_type,
                },
            )
            self._session.add(document_version)
        else:
            document_version.ingestion_run_id = run.id
            document_version.version_label = (
                manifest_document.manifest_id or stored.content_hash[:12]
            )
            document_version.source_hash = stored.content_hash
            document_version.artifact_uri = str(stored.path)
            document_version.state = DocumentVersionState.CURRENT
            document_version.is_current = True
            document_version.metadata_json = {
                **document_version.metadata_json,
                "byte_size": stored.size_bytes,
                "mime_type": stored.mime_type,
                "document_type": manifest_document.document_type,
            }
        self._session.commit()
        return document_version

    def _upsert_artifact(
        self,
        *,
        document_version: DocumentVersion,
        source_url: str,
        stored: StoredArtifact,
    ) -> None:
        artifact = self._session.scalar(
            select(SourceArtifact).where(
                SourceArtifact.document_version_id == document_version.id,
                SourceArtifact.uri == str(stored.path),
            )
        )
        if artifact is None:
            artifact = SourceArtifact(
                document_version_id=document_version.id,
                kind=ArtifactKind.RAW_PDF,
                uri=str(stored.path),
                content_hash=stored.content_hash,
                mime_type=stored.mime_type,
                byte_size=stored.size_bytes,
            )
            self._session.add(artifact)
        else:
            artifact.kind = ArtifactKind.RAW_PDF
            artifact.content_hash = stored.content_hash
            artifact.mime_type = stored.mime_type
            artifact.byte_size = stored.size_bytes
        document_version.metadata_json = {
            **document_version.metadata_json,
            "source_url": source_url,
        }
        self._session.commit()

    def _upsert_pages_and_blocks(
        self,
        document_version: DocumentVersion,
        parsed: ParsedPdf,
    ) -> tuple[int, int]:
        page_count = 0
        block_count = 0
        seen_page_numbers: set[int] = set()
        for parsed_page in parsed.pages:
            seen_page_numbers.add(parsed_page.page_number)
            page = self._session.scalar(
                select(PdfPage).where(
                    PdfPage.document_version_id == document_version.id,
                    PdfPage.page_number == parsed_page.page_number,
                )
            )
            if page is None:
                page = PdfPage(
                    document_version_id=document_version.id,
                    page_number=parsed_page.page_number,
                )
                self._session.add(page)
                self._session.flush()
            page.text = parsed_page.text
            page.text_hash = parsed_page.text_hash
            page.width_points = parsed_page.width_points
            page.height_points = parsed_page.height_points
            page_count += 1
            block_count += self._upsert_blocks(document_version, page, parsed_page.blocks)

        stale_pages = self._session.scalars(
            select(PdfPage).where(
                PdfPage.document_version_id == document_version.id,
                PdfPage.page_number.not_in(seen_page_numbers),
            )
        ).all()
        for page in stale_pages:
            self._session.delete(page)

        document_version.metadata_json = {
            **document_version.metadata_json,
            "pdf_parse": parsed.diagnostics,
        }
        self._session.commit()
        return page_count, block_count

    def _upsert_blocks(
        self,
        document_version: DocumentVersion,
        page: PdfPage,
        parsed_blocks: Sequence[Any],
    ) -> int:
        seen_block_indexes: set[int] = set()
        for parsed_block in parsed_blocks:
            seen_block_indexes.add(parsed_block.block_index)
            block = self._session.scalar(
                select(PdfBlock).where(
                    PdfBlock.page_id == page.id,
                    PdfBlock.block_index == parsed_block.block_index,
                )
            )
            if block is None:
                block = PdfBlock(
                    document_version_id=document_version.id,
                    page_id=page.id,
                    block_index=parsed_block.block_index,
                )
                self._session.add(block)
            block.document_version_id = document_version.id
            block.block_type = parsed_block.block_type
            block.text = parsed_block.text
            block.text_hash = parsed_block.text_hash
            block.x0_points = parsed_block.x0_points
            block.y0_points = parsed_block.y0_points
            block.x1_points = parsed_block.x1_points
            block.y1_points = parsed_block.y1_points
            block.char_start = parsed_block.char_start
            block.char_end = parsed_block.char_end
            block.metadata_json = parsed_block.metadata

        self._session.execute(
            delete(PdfBlock).where(
                PdfBlock.page_id == page.id,
                PdfBlock.block_index.not_in(seen_block_indexes),
            )
        )
        return len(parsed_blocks)

    def _record_parse_diagnostics(
        self,
        *,
        run: IngestionRun,
        company: Company,
        document: SourceDocument,
        document_version: DocumentVersion,
        parsed: ParsedPdf,
    ) -> None:
        if not parsed.diagnostics["image_only_or_scanned"]:
            return
        self._record_failure(
            run=run,
            stage="parse",
            message="PDF contains no extractable text; possible scanned or image-only document.",
            company_id=company.id,
            source_document_id=document.id,
            retryable=False,
            details={
                "document_version_id": str(document_version.id),
                "page_count": parsed.page_count,
                "empty_pages": parsed.diagnostics["empty_pages"],
            },
        )

    def _record_failure(
        self,
        *,
        run: IngestionRun,
        stage: str,
        message: str,
        company_id: uuid.UUID | None = None,
        source_document_id: uuid.UUID | None = None,
        retryable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            IngestionFailure(
                run_id=run.id,
                company_id=company_id,
                source_document_id=source_document_id,
                stage=stage,
                message=message,
                retryable=retryable,
                details_json=details or {},
            )
        )
        self._session.commit()

    def _mark_failures_resolved(
        self,
        *,
        company_id: uuid.UUID,
        source_document_id: uuid.UUID,
    ) -> None:
        statement = select(IngestionFailure).where(
            IngestionFailure.company_id == company_id,
            IngestionFailure.source_document_id == source_document_id,
            IngestionFailure.resolved_at.is_(None),
        )
        resolved_at = datetime.now(UTC)
        for failure in self._session.scalars(statement):
            failure.resolved_at = resolved_at
        self._session.commit()

    def _count_failures(self, run_id: uuid.UUID) -> int:
        return len(
            self._session.scalars(
                select(IngestionFailure).where(IngestionFailure.run_id == run_id)
            ).all()
        )


def build_investor_pdf_client_from_settings(settings: Settings) -> InvestorPdfClient:
    return InvestorPdfClient(
        user_agent=settings.investor_pdf_user_agent,
        timeout_seconds=settings.investor_pdf_request_timeout_seconds,
        retry_attempts=settings.investor_pdf_retry_attempts,
    )


def _stable_source_id(manifest_document: InvestorPdfManifestDocument) -> str:
    if manifest_document.manifest_id:
        return f"manifest:{manifest_document.manifest_id}"
    digest = hashlib.sha256(manifest_document.source_url.encode("utf-8")).hexdigest()[:24]
    return f"url:{digest}"


def _company_path_segment(manifest_document: InvestorPdfManifestDocument) -> str:
    return _safe_path_segment(
        manifest_document.ticker
        or manifest_document.cik
        or manifest_document.company_name.lower().replace(" ", "-")
    )


def _safe_path_segment(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "unknown"


def _stage_for_exception(exc: Exception) -> str:
    if isinstance(exc, PdfParseError):
        return "parse"
    if isinstance(exc, InvestorPdfClientError):
        return "download"
    return "document"
