from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from company_lens import cli
from company_lens.config import Settings
from company_lens.db.base import Base
from company_lens.db.models import (
    Company,
    DocumentChunk,
    DocumentKind,
    DocumentSummary,
    DocumentVersion,
    DocumentVersionState,
    FilingSection,
    PdfPage,
    SectionSummary,
    SourceDocument,
)
from company_lens.processing.service import DocumentProcessingOptions, DocumentProcessingService
from company_lens.processing.stats import corpus_stats, demo_chunks


def test_processes_sec_sections_into_summaries_and_chunks(
    session: Session,
    tmp_path: Path,
) -> None:
    text = (
        "Item 1. Business\n"
        "Cloudflare provides connectivity cloud services for customers around the world. "
        "Revenue increased because more enterprise customers adopted the platform. "
        "Management expects durable demand from security and developer use cases. "
        "Item 1A. Risk Factors\n"
        "Forward-looking statements actual results may differ materially. "
        "Competition risk remains meaningful because customers compare platform vendors. "
        "Competition risk remains meaningful because customers compare platform vendors. "
        "Macroeconomic conditions may reduce customer spending."
    )
    document_version = _sec_document_version(session, tmp_path, text)
    business_start = text.index("Item 1. Business")
    risk_start = text.index("Item 1A. Risk Factors")
    session.add_all(
        [
            FilingSection(
                document_version_id=document_version.id,
                section_code="business",
                title="Business",
                ordinal_path="business",
                heading_level=1,
                char_start=business_start,
                char_end=risk_start,
                content_hash="business-hash",
            ),
            FilingSection(
                document_version_id=document_version.id,
                section_code="risk_factors",
                title="Risk Factors",
                ordinal_path="risk_factors",
                heading_level=1,
                char_start=risk_start,
                char_end=len(text),
                content_hash="risk-hash",
            ),
        ]
    )
    session.commit()

    result = DocumentProcessingService(session=session).process(
        DocumentProcessingOptions(
            document_version_ids=(document_version.id,),
            max_tokens=12,
            overlap_tokens=0,
            force=True,
        )
    )

    summaries = session.scalars(select(DocumentSummary)).all()
    section_summaries = session.scalars(select(SectionSummary)).all()
    chunks = session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)).all()

    assert result.documents_processed == 1
    assert result.sections_seen == 2
    assert result.chunks_written == len(chunks)
    assert result.boilerplate_chunks_removed >= 1
    assert len(summaries) == 1
    assert len(section_summaries) == 2
    assert chunks
    assert chunks[0].metadata_json["chunking_version"] == "chunking.v1"
    assert chunks[0].char_start is not None
    assert chunks[0].section_id in {summary.section_id for summary in section_summaries}


def test_processes_pdf_pages_with_page_lineage(
    session: Session,
    tmp_path: Path,
) -> None:
    document_version = _pdf_document_version(session, tmp_path)
    session.add_all(
        [
            PdfPage(
                document_version_id=document_version.id,
                page_number=1,
                text="Revenue increased year over year as enterprise customers expanded usage.",
                text_hash="page-1",
            ),
            PdfPage(
                document_version_id=document_version.id,
                page_number=2,
                text="Risks include competition, customer budget pressure, and platform outages.",
                text_hash="page-2",
            ),
        ]
    )
    session.commit()

    result = DocumentProcessingService(session=session).process(
        DocumentProcessingOptions(
            document_version_ids=(document_version.id,),
            max_tokens=16,
            overlap_tokens=0,
            force=True,
        )
    )

    section = session.scalar(
        select(FilingSection).where(FilingSection.ordinal_path == "pdf.document")
    )
    chunks = session.scalars(select(DocumentChunk).order_by(DocumentChunk.chunk_index)).all()

    assert result.documents_processed == 1
    assert section is not None
    assert section.page_start == 1
    assert section.page_end == 2
    assert chunks
    assert {chunk.page_start for chunk in chunks} == {1}
    assert {chunk.page_end for chunk in chunks} == {2}


def test_processing_is_idempotent_and_cli_reports_stats(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    document_version = _sec_document_version(
        session,
        tmp_path,
        "Business text with revenue growth and customer expansion. Risk text with competition.",
    )

    service = DocumentProcessingService(session=session)
    first = service.process(DocumentProcessingOptions(document_version_ids=(document_version.id,)))
    second = service.process(DocumentProcessingOptions(document_version_ids=(document_version.id,)))

    assert first.documents_processed == 1
    assert second.documents_skipped == 1
    assert corpus_stats(session)["document_chunks"] > 0
    assert demo_chunks(session, limit=1)

    factory = sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    settings = Settings(database_url="sqlite+pysqlite:///unused.db")
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_session_factory", lambda _: factory)

    exit_code = cli.main(["corpus-stats", "--demo-chunks", "1"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert '"document_chunks"' in output
    assert '"demo_chunks"' in output


def _sec_document_version(session: Session, tmp_path: Path, text: str) -> DocumentVersion:
    company = _company(session)
    document = SourceDocument(
        company_id=company.id,
        kind=DocumentKind.SEC_FILING,
        source_system="sec_edgar",
        stable_source_id="0000000000-26-000001:form10k.htm",
        source_url="https://example.com/form10k.htm",
        title="Cloudflare 10-K",
        accession_number="0000000000-26-000001",
        filing_form="10-K",
        metadata_json={},
    )
    session.add(document)
    session.flush()
    artifact_path = tmp_path / "form10k.htm"
    artifact_path.write_text(text, encoding="utf-8")
    document_version = DocumentVersion(
        document_id=document.id,
        version_label="0000000000-26-000001",
        content_hash="sec-content-hash",
        source_hash="sec-content-hash",
        artifact_uri=str(artifact_path),
        state=DocumentVersionState.CURRENT,
        is_current=True,
        metadata_json={"mime_type": "text/html"},
    )
    session.add(document_version)
    session.commit()
    return document_version


def _pdf_document_version(session: Session, tmp_path: Path) -> DocumentVersion:
    company = _company(session)
    document = SourceDocument(
        company_id=company.id,
        kind=DocumentKind.INVESTOR_PDF,
        source_system="investor_relations_pdf",
        stable_source_id="manifest:net-demo",
        source_url="https://example.com/investor.pdf",
        title="Cloudflare investor presentation",
        metadata_json={},
    )
    session.add(document)
    session.flush()
    artifact_path = tmp_path / "investor.pdf"
    artifact_path.write_bytes(b"%PDF-1.4")
    document_version = DocumentVersion(
        document_id=document.id,
        version_label="net-demo",
        content_hash="pdf-content-hash",
        source_hash="pdf-content-hash",
        artifact_uri=str(artifact_path),
        state=DocumentVersionState.CURRENT,
        is_current=True,
        metadata_json={"mime_type": "application/pdf"},
    )
    session.add(document_version)
    session.commit()
    return document_version


def _company(session: Session) -> Company:
    company = session.scalar(select(Company).where(Company.cik == "0001477333"))
    if company is not None:
        return company
    company = Company(
        legal_name="Cloudflare, Inc.",
        display_name="Cloudflare",
        cik="0001477333",
    )
    session.add(company)
    session.flush()
    return company


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session
