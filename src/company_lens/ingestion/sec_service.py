from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from company_lens.config import Settings
from company_lens.db.models import (
    ArtifactKind,
    Company,
    CompanyIdentifier,
    CompanyTicker,
    DocumentKind,
    DocumentVersion,
    DocumentVersionState,
    Exchange,
    FilingSection,
    IdentifierKind,
    IngestionFailure,
    IngestionRun,
    IngestionRunStatus,
    SourceArtifact,
    SourceDocument,
)
from company_lens.ingestion.artifacts import ArtifactStore, StoredArtifact
from company_lens.ingestion.sec_client import SecClient, SecClientError, SecFilingMetadata
from company_lens.ingestion.sec_sections import detect_high_value_sections

DEFAULT_FORMS = ("10-K", "10-Q", "8-K")
INITIAL_COMPANY_UNIVERSE = {
    "NET": "Cloudflare",
    "DDOG": "Datadog",
    "MDB": "MongoDB",
    "SNOW": "Snowflake",
    "ESTC": "Elastic",
}
EXHIBIT_PREFIXES = ("EX-", "EX_")
SEC_SOURCE_SYSTEM = "sec_edgar"
SEC_TICKER_EXCHANGE_CODE = "SEC"


@dataclass(frozen=True)
class SecIngestionOptions:
    tickers: tuple[str, ...]
    forms: tuple[str, ...] = DEFAULT_FORMS
    limit_per_form: int = 3
    download_exhibits: bool = False


@dataclass(frozen=True)
class SecIngestionResult:
    run_id: str
    status: str
    companies_seen: int
    filings_seen: int
    artifacts_seen: int
    failures: int


class SecIngestionService:
    def __init__(
        self,
        *,
        session: Session,
        client: SecClient,
        artifact_store: ArtifactStore,
    ) -> None:
        self._session = session
        self._client = client
        self._artifact_store = artifact_store

    def ingest(self, options: SecIngestionOptions) -> SecIngestionResult:
        target = ",".join(options.tickers)
        run = IngestionRun(
            source_name=SEC_SOURCE_SYSTEM,
            status=IngestionRunStatus.STARTED,
            parameters={
                "target": target,
                "forms": list(options.forms),
                "limit_per_form": options.limit_per_form,
                "download_exhibits": options.download_exhibits,
            },
        )
        self._session.add(run)
        self._session.commit()

        companies_seen = 0
        filings_seen = 0
        artifacts_seen = 0

        for ticker in options.tickers:
            try:
                company, submissions = self._prepare_company(ticker)
                self._mark_ticker_failures_resolved(ticker)
                self._mark_failures_resolved(
                    company_id=company.id,
                    source_document_id=None,
                    stage="company",
                )
                companies_seen += 1
                artifacts_seen += self._store_submissions_artifact(run, company, submissions)
                filings = self._client.iter_recent_filings(
                    company.cik or "",
                    company.display_name,
                    submissions,
                    forms=options.forms,
                    limit_per_form=options.limit_per_form,
                )
                for filing_metadata in filings:
                    document: SourceDocument | None = None
                    try:
                        document = self._upsert_filing_document(company, filing_metadata)
                        filings_seen += 1
                        document_version = self._download_primary_document(
                            run,
                            document,
                            filing_metadata,
                        )
                        artifacts_seen += 1
                        if options.download_exhibits:
                            artifacts_seen += self._download_exhibits(
                                document_version,
                                filing_metadata,
                            )
                        self._mark_failures_resolved(
                            company_id=company.id,
                            source_document_id=document.id,
                            stage="filing",
                        )
                    except Exception as exc:
                        self._record_failure(
                            run=run,
                            stage="filing",
                            message=str(exc),
                            company_id=company.id,
                            source_document_id=document.id if document is not None else None,
                            details={
                                "ticker": ticker,
                                "accession_number": filing_metadata.accession_number,
                            },
                        )
            except Exception as exc:
                self._record_failure(
                    run=run,
                    stage="company",
                    message=str(exc),
                    details={"ticker": ticker},
                )

        failure_count = self._count_failures(run.id)
        run.status = (
            IngestionRunStatus.SUCCEEDED if failure_count == 0 else IngestionRunStatus.PARTIAL
        )
        run.completed_at = datetime.now(UTC)
        run.parameters = {
            **run.parameters,
            "companies_seen": companies_seen,
            "filings_seen": filings_seen,
            "artifacts_seen": artifacts_seen,
            "failures": failure_count,
        }
        self._session.commit()

        return SecIngestionResult(
            run_id=str(run.id),
            status="success" if failure_count == 0 else "partial_failed",
            companies_seen=companies_seen,
            filings_seen=filings_seen,
            artifacts_seen=artifacts_seen,
            failures=failure_count,
        )

    def _prepare_company(self, ticker: str) -> tuple[Company, dict[str, Any]]:
        resolved = self._client.resolve_ticker(ticker)
        submissions = self._client.fetch_submissions(resolved.cik)
        company = self._session.scalar(select(Company).where(Company.cik == resolved.cik))
        if company is None:
            company = Company(
                legal_name=resolved.name,
                display_name=resolved.name,
                cik=resolved.cik,
            )
            self._session.add(company)
        else:
            company.legal_name = resolved.name
            company.display_name = resolved.name
            company.cik = resolved.cik
        self._session.flush()
        self._upsert_cik_identifier(company, resolved.cik)
        self._upsert_ticker(company, resolved.ticker)
        self._session.commit()
        return company, submissions

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
                    source=SEC_SOURCE_SYSTEM,
                )
            )
        else:
            identifier.company_id = company.id
            identifier.source = SEC_SOURCE_SYSTEM

    def _upsert_ticker(self, company: Company, ticker: str) -> None:
        exchange = self._session.scalar(
            select(Exchange).where(Exchange.code == SEC_TICKER_EXCHANGE_CODE)
        )
        if exchange is None:
            exchange = Exchange(
                mic=SEC_TICKER_EXCHANGE_CODE,
                code=SEC_TICKER_EXCHANGE_CODE,
                name="SEC company ticker mapping",
                country_code="US",
            )
            self._session.add(exchange)
            self._session.flush()

        company_ticker = self._session.scalar(
            select(CompanyTicker).where(
                CompanyTicker.exchange_id == exchange.id,
                CompanyTicker.symbol == ticker,
                CompanyTicker.valid_from.is_(None),
            )
        )
        if company_ticker is None:
            self._session.add(
                CompanyTicker(
                    company_id=company.id,
                    exchange_id=exchange.id,
                    symbol=ticker,
                    is_primary=True,
                )
            )
        else:
            company_ticker.company_id = company.id
            company_ticker.is_primary = True

    def _store_submissions_artifact(
        self,
        run: IngestionRun,
        company: Company,
        submissions: dict[str, Any],
    ) -> int:
        url = f"https://data.sec.gov/submissions/CIK{company.cik}.json"
        stored = self._artifact_store.store_json(
            relative_path=Path(company.cik or "unknown-cik") / "submissions.json",
            payload=submissions,
        )
        document = self._upsert_source_document(
            company=company,
            kind=DocumentKind.OTHER,
            stable_source_id=f"sec-submissions:{company.cik}",
            source_url=url,
            title=f"{company.display_name} SEC submissions metadata",
            accession_number=None,
            filing_form=None,
            filing_date=None,
            report_date=None,
            metadata={"cik": company.cik},
        )
        document_version = self._upsert_document_version(
            run=run,
            document=document,
            stored=stored,
            version_label="submissions",
        )
        self._upsert_artifact(
            document_version=document_version,
            kind=ArtifactKind.OTHER,
            source_url=url,
            stored=stored,
        )
        return 1

    def _upsert_filing_document(
        self,
        company: Company,
        metadata: SecFilingMetadata,
    ) -> SourceDocument:
        return self._upsert_source_document(
            company=company,
            kind=DocumentKind.SEC_FILING,
            stable_source_id=f"{metadata.accession_number}:{metadata.primary_document}",
            source_url=metadata.source_url,
            title=f"{company.display_name} {metadata.form_type} {metadata.filing_date}",
            accession_number=metadata.accession_number,
            filing_form=metadata.form_type,
            filing_date=metadata.filing_date,
            report_date=metadata.report_date,
            metadata={
                **metadata.metadata,
                "primary_document": metadata.primary_document,
                "source_index_url": metadata.source_index_url,
            },
        )

    def _upsert_source_document(
        self,
        *,
        company: Company,
        kind: DocumentKind,
        stable_source_id: str,
        source_url: str,
        title: str,
        accession_number: str | None,
        filing_form: str | None,
        filing_date: date | None,
        report_date: date | None,
        metadata: dict[str, Any],
    ) -> SourceDocument:
        document = self._session.scalar(
            select(SourceDocument).where(
                SourceDocument.source_system == SEC_SOURCE_SYSTEM,
                SourceDocument.stable_source_id == stable_source_id,
            )
        )
        if document is None:
            document = SourceDocument(
                company_id=company.id,
                kind=kind,
                source_system=SEC_SOURCE_SYSTEM,
                stable_source_id=stable_source_id,
                source_url=source_url,
                title=title,
                accession_number=accession_number,
                filing_form=filing_form,
                filing_date=filing_date,
                report_date=report_date,
                metadata_json=metadata,
            )
            self._session.add(document)
        else:
            document.company_id = company.id
            document.kind = kind
            document.source_url = source_url
            document.title = title
            document.accession_number = accession_number
            document.filing_form = filing_form
            document.filing_date = filing_date
            document.report_date = report_date
            document.metadata_json = metadata
        self._session.commit()
        return document

    def _download_primary_document(
        self,
        run: IngestionRun,
        document: SourceDocument,
        metadata: SecFilingMetadata,
    ) -> DocumentVersion:
        content, mime_type = self._client.get_bytes(metadata.source_url)
        relative_path = (
            Path(metadata.cik)
            / metadata.accession_number.replace("-", "")
            / metadata.primary_document
        )
        stored = self._artifact_store.store_bytes(
            relative_path=relative_path,
            content=content,
            mime_type=mime_type,
        )
        document_version = self._upsert_document_version(
            run=run,
            document=document,
            stored=stored,
            version_label=metadata.accession_number,
        )
        self._upsert_artifact(
            document_version=document_version,
            kind=_artifact_kind_for_mime_type(mime_type),
            source_url=metadata.source_url,
            stored=stored,
        )
        self._upsert_sections(document_version, content, mime_type)
        return document_version

    def _download_exhibits(
        self,
        document_version: DocumentVersion,
        metadata: SecFilingMetadata,
    ) -> int:
        count = 0
        documents = self._client.fetch_archive_documents(metadata.cik, metadata.accession_number)
        for document in documents:
            if document.document_name == metadata.primary_document:
                continue
            if not document.document_type.upper().startswith(EXHIBIT_PREFIXES):
                continue
            content, mime_type = self._client.get_bytes(document.source_url)
            relative_path = (
                Path(metadata.cik)
                / metadata.accession_number.replace("-", "")
                / document.document_name
            )
            stored = self._artifact_store.store_bytes(
                relative_path=relative_path,
                content=content,
                mime_type=mime_type,
            )
            self._upsert_artifact(
                document_version=document_version,
                kind=ArtifactKind.OTHER,
                source_url=document.source_url,
                stored=stored,
            )
            count += 1
        return count

    def _upsert_document_version(
        self,
        *,
        run: IngestionRun,
        document: SourceDocument,
        stored: StoredArtifact,
        version_label: str,
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
                version_label=version_label,
                content_hash=stored.content_hash,
                source_hash=stored.content_hash,
                artifact_uri=str(stored.path),
                state=DocumentVersionState.CURRENT,
                is_current=True,
                metadata_json={"byte_size": stored.size_bytes, "mime_type": stored.mime_type},
            )
            self._session.add(document_version)
        else:
            document_version.ingestion_run_id = run.id
            document_version.version_label = version_label
            document_version.source_hash = stored.content_hash
            document_version.artifact_uri = str(stored.path)
            document_version.state = DocumentVersionState.CURRENT
            document_version.is_current = True
            document_version.metadata_json = {
                "byte_size": stored.size_bytes,
                "mime_type": stored.mime_type,
            }
        self._session.commit()
        return document_version

    def _upsert_artifact(
        self,
        *,
        document_version: DocumentVersion,
        kind: ArtifactKind,
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
                kind=kind,
                uri=str(stored.path),
                content_hash=stored.content_hash,
                mime_type=stored.mime_type,
                byte_size=stored.size_bytes,
            )
            self._session.add(artifact)
        else:
            artifact.kind = kind
            artifact.content_hash = stored.content_hash
            artifact.mime_type = stored.mime_type
            artifact.byte_size = stored.size_bytes
        document_version.metadata_json = {
            **document_version.metadata_json,
            "source_url": source_url,
        }
        self._session.commit()

    def _upsert_sections(
        self,
        document_version: DocumentVersion,
        content: bytes,
        mime_type: str | None,
    ) -> None:
        for detected in detect_high_value_sections(content, content_type=mime_type):
            section = self._session.scalar(
                select(FilingSection).where(
                    FilingSection.document_version_id == document_version.id,
                    FilingSection.ordinal_path == detected.section_key,
                )
            )
            if section is None:
                section = FilingSection(
                    document_version_id=document_version.id,
                    section_code=detected.section_key,
                    title=detected.title,
                    ordinal_path=detected.section_key,
                    heading_level=1,
                    char_start=detected.start_offset,
                    char_end=detected.end_offset,
                    content_hash=detected.text_hash,
                )
                self._session.add(section)
            else:
                section.section_code = detected.section_key
                section.title = detected.title
                section.char_start = detected.start_offset
                section.char_end = detected.end_offset
                section.content_hash = detected.text_hash
        self._session.commit()

    def _record_failure(
        self,
        *,
        run: IngestionRun,
        stage: str,
        message: str,
        company_id: uuid.UUID | None = None,
        source_document_id: uuid.UUID | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self._session.add(
            IngestionFailure(
                run_id=run.id,
                company_id=company_id,
                source_document_id=source_document_id,
                stage=stage,
                message=message,
                retryable=True,
                details_json=details or {},
            )
        )
        self._session.commit()

    def _mark_ticker_failures_resolved(self, ticker: str) -> None:
        statement = select(IngestionFailure).where(
            IngestionFailure.company_id.is_(None),
            IngestionFailure.stage == "company",
            IngestionFailure.resolved_at.is_(None),
        )
        resolved_at = datetime.now(UTC)
        for failure in self._session.scalars(statement):
            if str(failure.details_json.get("ticker", "")).upper() == ticker.upper():
                failure.resolved_at = resolved_at
        self._session.commit()

    def _mark_failures_resolved(
        self,
        *,
        company_id: uuid.UUID,
        source_document_id: uuid.UUID | None,
        stage: str,
    ) -> None:
        statement = select(IngestionFailure).where(
            IngestionFailure.company_id == company_id,
            IngestionFailure.stage == stage,
            IngestionFailure.resolved_at.is_(None),
        )
        if source_document_id is None:
            statement = statement.where(IngestionFailure.source_document_id.is_(None))
        else:
            statement = statement.where(IngestionFailure.source_document_id == source_document_id)
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


def build_sec_client_from_settings(settings: Settings) -> SecClient:
    user_agent = settings.sec_user_agent or os.getenv("SEC_USER_AGENT")
    if not user_agent:
        raise SecClientError(
            "Set COMPANY_LENS_SEC_USER_AGENT or SEC_USER_AGENT before running SEC ingestion."
        )
    return SecClient(
        user_agent=user_agent,
        timeout_seconds=settings.sec_request_timeout_seconds,
        retry_attempts=settings.sec_retry_attempts,
        rate_limit_per_second=settings.sec_rate_limit_per_second,
    )


def build_default_options(
    *,
    tickers: Sequence[str] | None,
    all_companies: bool,
    forms: Sequence[str],
    settings: Settings,
    download_exhibits: bool,
) -> SecIngestionOptions:
    selected_tickers = tuple(ticker.upper() for ticker in (tickers or ()))
    if all_companies:
        selected_tickers = tuple(INITIAL_COMPANY_UNIVERSE)
    if not selected_tickers:
        raise ValueError("Provide at least one ticker or use --all.")
    return SecIngestionOptions(
        tickers=selected_tickers,
        forms=tuple(form.upper() for form in forms),
        limit_per_form=settings.sec_filings_per_form,
        download_exhibits=download_exhibits or settings.sec_download_exhibits,
    )


def _artifact_kind_for_mime_type(mime_type: str | None) -> ArtifactKind:
    if mime_type and "html" in mime_type.lower():
        return ArtifactKind.RAW_HTML
    if mime_type and "text" in mime_type.lower():
        return ArtifactKind.RAW_TEXT
    return ArtifactKind.OTHER
