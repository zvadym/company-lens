from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from company_lens import cli
from company_lens.config import Settings
from company_lens.db.base import Base
from company_lens.db.models import (
    IngestionFailure,
    PdfBlock,
    PdfPage,
    SourceArtifact,
    SourceDocument,
)
from company_lens.ingestion.artifacts import ArtifactStore
from company_lens.ingestion.pdf_manifest import InvestorPdfManifestDocument
from company_lens.ingestion.pdf_parser import (
    ParsedPdf,
    ParsedPdfBlock,
    ParsedPdfPage,
    PdfParseError,
    PdfParser,
)
from company_lens.ingestion.pdf_service import (
    InvestorPdfIngestionOptions,
    InvestorPdfIngestionService,
)

PDF_URL = "https://example.com/investor.pdf"
PDF_BYTES = b"%PDF-1.4 fake fixture"


@dataclass
class FakePdfClient:
    content: bytes = PDF_BYTES
    mime_type: str | None = "application/pdf"

    def get_bytes(self, url: str) -> tuple[bytes, str | None]:
        assert url == PDF_URL
        return self.content, self.mime_type


class ContextFakePdfClient(FakePdfClient):
    def __enter__(self) -> ContextFakePdfClient:
        return self

    def __exit__(self, *args: object) -> None:
        return None


class FakePdfParser:
    def __init__(self, parsed: ParsedPdf | None = None, error: Exception | None = None) -> None:
        self.parsed = parsed or _parsed_pdf()
        self.error = error

    def parse(self, content: bytes) -> ParsedPdf:
        assert content == PDF_BYTES
        if self.error is not None:
            raise self.error
        return self.parsed


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session


def test_investor_pdf_ingestion_is_idempotent_and_preserves_page_blocks(
    session: Session,
    tmp_path,
) -> None:
    service = InvestorPdfIngestionService(
        session=session,
        client=FakePdfClient(),  # type: ignore[arg-type]
        artifact_store=ArtifactStore(tmp_path),
        parser=FakePdfParser(),  # type: ignore[arg-type]
    )
    options = InvestorPdfIngestionOptions(documents=(_manifest_document(),))

    first_result = service.ingest(options)
    second_result = service.ingest(options)

    documents = session.scalars(select(SourceDocument)).all()
    artifacts = session.scalars(select(SourceArtifact)).all()
    pages = session.scalars(select(PdfPage).order_by(PdfPage.page_number)).all()
    blocks = session.scalars(select(PdfBlock).order_by(PdfBlock.block_index)).all()
    failures = session.scalars(select(IngestionFailure)).all()

    assert first_result.status == "success"
    assert second_result.status == "success"
    assert len(documents) == 1
    assert documents[0].title == "Q4 2025 investor presentation"
    assert len(artifacts) == 1
    assert artifacts[0].uri.endswith("NET/manifest-net-q4-2025.pdf")
    assert len(pages) == 2
    assert pages[0].page_number == 1
    assert pages[0].text == "Revenue increased year over year."
    assert len(blocks) == 3
    assert blocks[0].page_id == pages[0].id
    assert blocks[0].text == "Revenue increased"
    assert blocks[0].x0_points == Decimal("72.00")
    assert not failures


def test_investor_pdf_ingestion_records_malformed_pdf_failure(
    session: Session,
    tmp_path,
) -> None:
    service = InvestorPdfIngestionService(
        session=session,
        client=FakePdfClient(),  # type: ignore[arg-type]
        artifact_store=ArtifactStore(tmp_path),
        parser=FakePdfParser(error=PdfParseError("broken pdf")),  # type: ignore[arg-type]
    )

    result = service.ingest(InvestorPdfIngestionOptions(documents=(_manifest_document(),)))
    failures = session.scalars(select(IngestionFailure)).all()

    assert result.status == "partial_failed"
    assert result.documents_seen == 0
    assert result.failures == 1
    assert len(failures) == 1
    assert failures[0].stage == "parse"
    assert failures[0].retryable is False
    assert "broken pdf" in failures[0].message


def test_investor_pdf_ingestion_reports_image_only_pdf(
    session: Session,
    tmp_path,
) -> None:
    parsed = ParsedPdf(
        page_count=1,
        pages=(
            ParsedPdfPage(
                page_number=1,
                text=None,
                text_hash=None,
                width_points=Decimal("612.00"),
                height_points=Decimal("792.00"),
                blocks=(),
                diagnostics={"empty_text": True, "block_count": 0, "word_count": 0},
            ),
        ),
        diagnostics={
            "parser": "pdfplumber",
            "page_count": 1,
            "empty_pages": [1],
            "pages_without_blocks": [1],
            "image_only_or_scanned": True,
            "coordinate_system": "pdfplumber_top_left_points",
        },
    )
    service = InvestorPdfIngestionService(
        session=session,
        client=FakePdfClient(),  # type: ignore[arg-type]
        artifact_store=ArtifactStore(tmp_path),
        parser=FakePdfParser(parsed=parsed),  # type: ignore[arg-type]
    )

    result = service.ingest(InvestorPdfIngestionOptions(documents=(_manifest_document(),)))
    pages = session.scalars(select(PdfPage)).all()
    failures = session.scalars(select(IngestionFailure)).all()

    assert result.status == "partial_failed"
    assert result.documents_seen == 1
    assert result.pages_seen == 1
    assert result.blocks_seen == 0
    assert len(pages) == 1
    assert len(failures) == 1
    assert failures[0].stage == "parse"
    assert failures[0].retryable is False
    assert "no extractable text" in failures[0].message


def test_pdf_parser_extracts_text_lines_from_multi_page_pdf() -> None:
    parsed = PdfParser().parse(
        _minimal_text_pdf(
            (
                "Cloudflare revenue increased",
                "Investor presentation risks",
            )
        )
    )

    assert parsed.page_count == 2
    assert parsed.diagnostics["image_only_or_scanned"] is False
    assert parsed.pages[0].page_number == 1
    assert "Cloudflare revenue increased" in (parsed.pages[0].text or "")
    assert parsed.pages[0].blocks
    assert parsed.pages[0].blocks[0].text is not None
    assert parsed.pages[0].blocks[0].x0_points is not None


def test_cli_ingests_configured_pdf(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    manifest_path = tmp_path / "manifest.yaml"
    manifest_path.write_text(
        f"""
documents:
  - id: net-cli-test
    company_name: Cloudflare
    ticker: NET
    cik: "1477333"
    title: CLI investor presentation
    document_type: investor_presentation
    fiscal_year: 2025
    fiscal_period: Q4
    period_end: 2025-12-31
    url: {PDF_URL}
""".strip(),
        encoding="utf-8",
    )
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'company_lens.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    settings = Settings(
        database_url="sqlite+pysqlite:///unused.db",
        investor_pdf_artifact_root=tmp_path / "artifacts",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "build_session_factory", lambda _: factory)
    monkeypatch.setattr(
        cli,
        "build_investor_pdf_client_from_settings",
        lambda _: ContextFakePdfClient(
            content=_minimal_text_pdf(("Revenue increased", "Risks include competition"))
        ),
    )

    exit_code = cli.main(["ingest-pdfs", "--manifest", str(manifest_path)])

    with factory() as session:
        pages = session.scalars(select(PdfPage)).all()
        blocks = session.scalars(select(PdfBlock)).all()

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Investor PDF ingestion completed" in output
    assert "status=success" in output
    assert len(pages) == 2
    assert blocks


def _manifest_document() -> InvestorPdfManifestDocument:
    return InvestorPdfManifestDocument(
        company_name="Cloudflare",
        source_url=PDF_URL,
        title="Q4 2025 investor presentation",
        document_type="investor_presentation",
        manifest_id="net-q4-2025",
        ticker="NET",
        cik="0001477333",
        period_end=None,
        fiscal_year=2025,
        fiscal_period="Q4",
        metadata={"reviewed": True},
    )


def _parsed_pdf() -> ParsedPdf:
    return ParsedPdf(
        page_count=2,
        pages=(
            ParsedPdfPage(
                page_number=1,
                text="Revenue increased year over year.",
                text_hash="page-1-hash",
                width_points=Decimal("612.00"),
                height_points=Decimal("792.00"),
                blocks=(
                    ParsedPdfBlock(
                        block_index=0,
                        block_type="text_line",
                        text="Revenue increased",
                        text_hash="block-1-hash",
                        x0_points=Decimal("72.00"),
                        y0_points=Decimal("100.00"),
                        x1_points=Decimal("240.00"),
                        y1_points=Decimal("114.00"),
                        char_start=0,
                        char_end=17,
                        metadata={"coordinate_system": "pdfplumber_top_left_points"},
                    ),
                    ParsedPdfBlock(
                        block_index=1,
                        block_type="text_line",
                        text="year over year.",
                        text_hash="block-2-hash",
                        x0_points=Decimal("72.00"),
                        y0_points=Decimal("120.00"),
                        x1_points=Decimal("200.00"),
                        y1_points=Decimal("134.00"),
                        char_start=18,
                        char_end=33,
                        metadata={"coordinate_system": "pdfplumber_top_left_points"},
                    ),
                ),
                diagnostics={"empty_text": False, "block_count": 2, "word_count": 5},
            ),
            ParsedPdfPage(
                page_number=2,
                text="Risk factors include competition.",
                text_hash="page-2-hash",
                width_points=Decimal("612.00"),
                height_points=Decimal("792.00"),
                blocks=(
                    ParsedPdfBlock(
                        block_index=0,
                        block_type="text_line",
                        text="Risk factors include competition.",
                        text_hash="block-3-hash",
                        x0_points=Decimal("72.00"),
                        y0_points=Decimal("100.00"),
                        x1_points=Decimal("270.00"),
                        y1_points=Decimal("114.00"),
                        char_start=0,
                        char_end=33,
                        metadata={"coordinate_system": "pdfplumber_top_left_points"},
                    ),
                ),
                diagnostics={"empty_text": False, "block_count": 1, "word_count": 4},
            ),
        ),
        diagnostics={
            "parser": "pdfplumber",
            "page_count": 2,
            "empty_pages": [],
            "pages_without_blocks": [],
            "image_only_or_scanned": False,
            "coordinate_system": "pdfplumber_top_left_points",
        },
    )


def _minimal_text_pdf(page_texts: tuple[str, ...]) -> bytes:
    page_kids = " ".join(f"{3 + index * 2} 0 R" for index in range(len(page_texts)))
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        (f"<< /Type /Pages /Kids [{page_kids}] /Count {len(page_texts)} >>").encode("ascii"),
    ]
    font_object_number = 3 + len(page_texts) * 2
    for index, text in enumerate(page_texts):
        page_object_number = 3 + index * 2
        content_object_number = page_object_number + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                f"/Resources << /Font << /F1 {font_object_number} 0 R >> >> "
                f"/Contents {content_object_number} 0 R >>"
            ).encode("ascii")
        )
        stream = f"BT /F1 18 Tf 72 720 Td ({_escape_pdf_text(text)}) Tj ET".encode("ascii")
        objects.append(
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    return _build_pdf(objects)


def _build_pdf(objects: list[bytes]) -> bytes:
    chunks = [b"%PDF-1.4\n"]
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(sum(len(chunk) for chunk in chunks))
        chunks.append(f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref_offset = sum(len(chunk) for chunk in chunks)
    chunks.append(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    chunks.append(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        chunks.append(f"{offset:010d} 00000 n \n".encode("ascii"))
    chunks.append(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    return b"".join(chunks)


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
