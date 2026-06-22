from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from company_lens.db.base import Base
from company_lens.db.models import (
    Company,
    FilingSection,
    IngestionFailure,
    SourceArtifact,
    SourceDocument,
)
from company_lens.ingestion.artifacts import ArtifactStore
from company_lens.ingestion.sec_client import SecCompany, SecFilingMetadata
from company_lens.ingestion.sec_service import SecIngestionOptions, SecIngestionService

CIK = "0001477333"
ACCESSION = "0001477333-26-000001"
SOURCE_URL = "https://www.sec.gov/Archives/edgar/data/1477333/000147733326000001/net.htm"
SOURCE_INDEX_URL = (
    "https://www.sec.gov/Archives/edgar/data/1477333/000147733326000001/0001477333-26-000001.txt"
)
FILING_HTML = b"""
<html><body>
Item 1. Business
Cloudflare operates a connectivity cloud.
Item 1A. Risk Factors
We face competition and operational risks.
Item 7. Management's Discussion and Analysis
Revenue increased year over year.
Item 7A. Quantitative and Qualitative Disclosures About Market Risk
Market risk discussion.
</body></html>
"""


class FakeSecClient:
    def __init__(self, *, fail_download: bool = False) -> None:
        self.fail_download = fail_download

    def resolve_ticker(self, ticker: str) -> SecCompany:
        assert ticker == "NET"
        return SecCompany(ticker="NET", cik=CIK, name="Cloudflare, Inc.")

    def fetch_submissions(self, cik: str) -> dict[str, object]:
        assert cik == CIK
        return {"filings": {"recent": {"form": ["10-K"]}}}

    def iter_recent_filings(
        self,
        cik: str,
        company_name: str,
        submissions: dict[str, object],
        *,
        forms: tuple[str, ...],
        limit_per_form: int,
    ) -> list[SecFilingMetadata]:
        assert cik == CIK
        assert company_name == "Cloudflare, Inc."
        assert submissions
        assert forms == ("10-K",)
        assert limit_per_form == 1
        return [
            SecFilingMetadata(
                cik=CIK,
                company_name=company_name,
                form_type="10-K",
                accession_number=ACCESSION,
                filing_date=date(2026, 2, 20),
                report_date=date(2025, 12, 31),
                primary_document="net.htm",
                source_url=SOURCE_URL,
                source_index_url=SOURCE_INDEX_URL,
                metadata={"form": "10-K"},
            )
        ]

    def get_bytes(self, url: str) -> tuple[bytes, str | None]:
        assert url == SOURCE_URL
        if self.fail_download:
            raise RuntimeError("download failed")
        return FILING_HTML, "text/html"

    def fetch_archive_documents(self, cik: str, accession_number: str) -> list[object]:
        assert cik == CIK
        assert accession_number == ACCESSION
        return []


class FakeCompanyFailureClient(FakeSecClient):
    def resolve_ticker(self, ticker: str) -> SecCompany:
        assert ticker == "NET"
        raise RuntimeError("ticker lookup failed")


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db_session:
        yield db_session


def test_sec_ingestion_is_idempotent_and_persists_sections(
    session: Session,
    tmp_path,
) -> None:
    service = SecIngestionService(
        session=session,
        client=FakeSecClient(),
        artifact_store=ArtifactStore(tmp_path),
    )
    options = SecIngestionOptions(tickers=("NET",), forms=("10-K",), limit_per_form=1)

    first_result = service.ingest(options)
    second_result = service.ingest(options)

    companies = session.scalars(select(Company)).all()
    filings = session.scalars(
        select(SourceDocument).where(SourceDocument.filing_form == "10-K")
    ).all()
    artifacts = session.scalars(select(SourceArtifact)).all()
    sections = session.scalars(select(FilingSection)).all()

    assert first_result.status == "success"
    assert second_result.status == "success"
    assert len(companies) == 1
    assert companies[0].display_name == "Cloudflare, Inc."
    assert len(filings) == 1
    assert filings[0].period_end == date(2025, 12, 31)
    assert filings[0].fiscal_year == 2025
    assert filings[0].fiscal_period == "FY"
    assert len(artifacts) == 2
    assert {section.section_code for section in sections} >= {
        "business",
        "risk_factors",
        "mda",
        "market_risk",
    }
    assert (tmp_path / CIK / "submissions.json").exists()
    assert (tmp_path / CIK / ACCESSION.replace("-", "") / "net.htm").exists()


def test_sec_ingestion_records_partial_failures(
    session: Session,
    tmp_path,
) -> None:
    service = SecIngestionService(
        session=session,
        client=FakeSecClient(fail_download=True),
        artifact_store=ArtifactStore(tmp_path),
    )

    result = service.ingest(
        SecIngestionOptions(tickers=("NET",), forms=("10-K",), limit_per_form=1)
    )
    failures = session.scalars(select(IngestionFailure)).all()

    assert result.status == "partial_failed"
    assert result.failures == 1
    assert len(failures) == 1
    assert failures[0].stage == "filing"
    assert failures[0].source_document_id is not None
    assert "download failed" in failures[0].message


def test_sec_ingestion_resolves_prior_retry_failures(
    session: Session,
    tmp_path,
) -> None:
    failing_service = SecIngestionService(
        session=session,
        client=FakeSecClient(fail_download=True),
        artifact_store=ArtifactStore(tmp_path),
    )
    options = SecIngestionOptions(tickers=("NET",), forms=("10-K",), limit_per_form=1)

    failing_result = failing_service.ingest(options)
    retry_service = SecIngestionService(
        session=session,
        client=FakeSecClient(),
        artifact_store=ArtifactStore(tmp_path),
    )
    retry_result = retry_service.ingest(options)
    failures = session.scalars(select(IngestionFailure)).all()

    assert failing_result.status == "partial_failed"
    assert retry_result.status == "success"
    assert len(failures) == 1
    assert failures[0].resolved_at is not None


def test_sec_ingestion_resolves_prior_company_failures_without_company_id(
    session: Session,
    tmp_path,
) -> None:
    failing_service = SecIngestionService(
        session=session,
        client=FakeCompanyFailureClient(),
        artifact_store=ArtifactStore(tmp_path),
    )
    options = SecIngestionOptions(tickers=("NET",), forms=("10-K",), limit_per_form=1)

    failing_result = failing_service.ingest(options)
    retry_service = SecIngestionService(
        session=session,
        client=FakeSecClient(),
        artifact_store=ArtifactStore(tmp_path),
    )
    retry_result = retry_service.ingest(options)
    failures = session.scalars(select(IngestionFailure)).all()

    assert failing_result.status == "partial_failed"
    assert retry_result.status == "success"
    assert len(failures) == 1
    assert failures[0].company_id is None
    assert failures[0].resolved_at is not None
