from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from company_lens.db.base import Base
from company_lens.db.models import FinancialFact, SourceArtifact, SourceDocument
from company_lens.financials.mapping import load_metric_mapping
from company_lens.financials.schemas import FinancialFactQuery
from company_lens.financials.service import FinancialFactQueryService
from company_lens.financials.tool import build_langchain_financial_facts_tool
from company_lens.ingestion.artifacts import ArtifactStore
from company_lens.ingestion.company_facts import (
    CompanyFactsIngestionOptions,
    CompanyFactsIngestionService,
    classify_period,
    parse_company_facts,
)
from company_lens.ingestion.sec_client import SecCompany

CIK = "0001477333"
FIXTURE = Path("tests/fixtures/sec/companyfacts-net.json")
MAPPING = Path("config/financial_metric_mappings.v1.yaml")


class FakeCompanyFactsClient:
    def __init__(self) -> None:
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def resolve_ticker(self, ticker: str) -> SecCompany:
        assert ticker == "NET"
        return SecCompany(ticker="NET", cik=CIK, name="Cloudflare, Inc.")

    def fetch_company_facts(self, cik: str) -> dict[str, object]:
        assert cik == CIK
        return self.payload


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db_session:
        yield db_session


def test_fixture_parser_classifies_periods_and_skips_missing_values() -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    facts, unmapped = parse_company_facts(
        payload,
        cik=CIK,
        mapping=load_metric_mapping(MAPPING),
    )

    assert len(facts) == 7
    assert unmapped == 1
    assert {fact.period_type for fact in facts} == {
        "annual",
        "quarter",
        "year_to_date",
        "instant",
    }
    assert sum(fact.is_amendment for fact in facts) == 1
    assert all(fact.source_url.startswith("https://www.sec.gov/Archives/") for fact in facts)


def test_ingestion_is_idempotent_and_retains_restatement_provenance(
    session: Session,
    tmp_path: Path,
) -> None:
    service = CompanyFactsIngestionService(
        session=session,
        client=FakeCompanyFactsClient(),  # type: ignore[arg-type]
        artifact_store=ArtifactStore(tmp_path),
    )
    options = CompanyFactsIngestionOptions(tickers=("NET",), mapping_path=MAPPING)

    first = service.ingest(options)
    second = service.ingest(options)
    facts = session.scalars(select(FinancialFact)).all()

    assert first.status == "success"
    assert first.facts_seen == 7
    assert first.facts_inserted == 6
    assert first.duplicates_skipped == 1
    assert second.facts_inserted == 0
    assert second.duplicates_skipped == 7
    assert len(facts) == 6
    annual_revenue = [
        fact
        for fact in facts
        if fact.canonical_metric == "revenue" and fact.period_type == "annual"
    ]
    assert len(annual_revenue) == 2
    assert {fact.form for fact in annual_revenue} == {"10-K", "10-K/A"}
    assert {fact.accession_number for fact in annual_revenue} == {
        "0001477333-25-000001",
        "0001477333-25-000002",
    }
    assert len(session.scalars(select(SourceDocument)).all()) == 1
    assert len(session.scalars(select(SourceArtifact)).all()) == 1


def test_typed_query_orders_observations_and_marks_conflicts(
    session: Session,
    tmp_path: Path,
) -> None:
    CompanyFactsIngestionService(
        session=session,
        client=FakeCompanyFactsClient(),  # type: ignore[arg-type]
        artifact_store=ArtifactStore(tmp_path),
    ).ingest(CompanyFactsIngestionOptions(tickers=("NET",), mapping_path=MAPPING))

    result = FinancialFactQueryService(session=session).query(
        FinancialFactQuery(tickers=("NET",), metrics=("revenue",))
    )

    assert len(result.observations) == 5
    assert [item.period_end for item in result.observations] == sorted(
        item.period_end for item in result.observations
    )
    assert sum(item.has_conflict for item in result.observations) == 2
    assert result.available_units == ("USD",)
    assert result.warnings == ("conflicting_or_restated_values_present",)


def test_missing_metric_returns_typed_empty_result(session: Session) -> None:
    result = FinancialFactQueryService(session=session).query(
        FinancialFactQuery(tickers=("NET",), metrics=("operating_income",))
    )

    assert result.observations == ()
    assert result.available_units == ()
    assert result.warnings == ("no_matching_financial_facts",)


def test_langchain_tool_exposes_typed_query_contract(session: Session) -> None:
    pytest.importorskip("langchain_core")
    tool = build_langchain_financial_facts_tool(FinancialFactQueryService(session=session))

    result = tool.invoke({"tickers": ["NET"], "metrics": ["revenue"]})

    assert tool.name == "query_financial_facts"
    assert result["observations"] == []
    assert result["warnings"] == ["no_matching_financial_facts"]


def test_period_classifier_distinguishes_quarter_from_year_to_date() -> None:
    from datetime import date

    assert (
        classify_period(start=date(2025, 4, 1), end=date(2025, 6, 30), fiscal_period="Q2")
        == "quarter"
    )
    assert (
        classify_period(start=date(2025, 1, 1), end=date(2025, 6, 30), fiscal_period="Q2")
        == "year_to_date"
    )
