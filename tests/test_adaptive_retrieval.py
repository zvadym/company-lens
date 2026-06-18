from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from company_lens.db.base import Base
from company_lens.db.models import (
    AliasKind,
    Company,
    CompanyAlias,
    CompanyTicker,
    DocumentChunk,
    DocumentKind,
    DocumentSummary,
    DocumentVersion,
    DocumentVersionState,
    Exchange,
    FilingSection,
    FinancialFact,
    SectionSummary,
    SourceDocument,
)
from company_lens.processing.text import content_hash
from company_lens.retrieval.adaptive import AdaptiveRetrievalService
from company_lens.retrieval.adaptive_schemas import AdaptiveRetrievalRequest
from company_lens.retrieval.planning import RetrievalPlanner
from company_lens.retrieval.resolution import EntityResolver


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        _seed_corpus(session)
        yield session


def test_exact_ticker_cik_and_accession_resolve_before_retrieval(session: Session) -> None:
    resolved = EntityResolver(session=session).resolve(
        "NET CIK 0001477333 filing 0001477333-26-000001 revenue"
    )

    companies = [entity for entity in resolved.entities if entity.kind == "company"]
    filing = next(entity for entity in resolved.entities if entity.kind == "filing")
    assert len(resolved.company_ids) == 1
    assert companies
    assert all(entity.status == "resolved" for entity in companies)
    assert filing.status == "resolved"
    assert resolved.accession_numbers == ("0001477333-26-000001",)
    assert resolved.metrics == ("revenue",)


def test_ambiguous_company_alias_is_explicit_and_prevents_guessing(session: Session) -> None:
    response = AdaptiveRetrievalService(session=session).retrieve(
        AdaptiveRetrievalRequest(query="What was Edge Cloud revenue in 2025?")
    )

    ambiguous = [
        entity for entity in response.resolved_query.entities if entity.status == "ambiguous"
    ]
    assert ambiguous
    assert len(ambiguous[0].candidates) == 2
    assert response.plan.strategy == "none"
    assert response.trace.abstained is True
    assert response.trace.abstention_reason == "ambiguous_entity"
    assert response.context == ()


def test_known_metric_uses_structured_fact_without_chunk_search(session: Session) -> None:
    response = AdaptiveRetrievalService(session=session).retrieve(
        AdaptiveRetrievalRequest(query="What was NET revenue in FY 2025?")
    )

    assert response.plan.strategy == "structured_only"
    assert response.context
    assert {item.kind for item in response.context} == {"financial_fact"}
    assert response.context[0].financial_fact_id is not None
    assert response.context[0].source_url == "https://example.com/cloudflare-2025"
    assert response.trace.attempts[0].action == "structured_financial_fact_lookup"
    assert response.trace.abstained is False


def test_detailed_context_orders_summaries_before_source_chunks(session: Session) -> None:
    response = AdaptiveRetrievalService(session=session).retrieve(
        AdaptiveRetrievalRequest(query="Cloudflare security platform evidence")
    )

    kinds = [item.kind for item in response.context]
    assert response.plan.strategy == "detailed"
    assert "document_summary" in kinds
    assert "section_summary" in kinds
    assert "chunk" in kinds
    assert kinds.index("document_summary") < kinds.index("section_summary") < kinds.index("chunk")
    assert all(item.citation_label and item.source_url for item in response.context)


def test_comparative_questions_receive_larger_context_budget(session: Session) -> None:
    resolver = EntityResolver(session=session)
    planner = RetrievalPlanner()

    simple = planner.plan(resolver.resolve("Cloudflare security platform"))
    comparative = planner.plan(
        resolver.resolve("Compare Cloudflare and Fastly risks in 2024 and 2025")
    )

    assert comparative.comparative is True
    assert comparative.budget.max_tokens > simple.budget.max_tokens
    assert comparative.budget.max_documents > simple.budget.max_documents
    assert len(comparative.filters.company_ids) == 2
    assert comparative.filters.fiscal_years == (2024, 2025)


def test_failed_recovery_is_bounded_and_every_attempt_changes_strategy(
    session: Session,
) -> None:
    response = AdaptiveRetrievalService(session=session).retrieve(
        AdaptiveRetrievalRequest(
            query="Cloudflare security evidence in 2099",
            max_attempts=3,
        )
    )

    strategies = [attempt.strategy for attempt in response.trace.attempts]
    assert len(strategies) == 3
    assert len(set(strategies)) == len(strategies)
    assert response.trace.abstained is True
    assert response.trace.abstention_reason == "insufficient_evidence_after_max_attempts"
    assert response.trace.final_context_tokens == 0


def _seed_corpus(session: Session) -> None:
    exchange = Exchange(mic="XNYS", code="NYSE", name="New York Stock Exchange")
    cloudflare = Company(
        legal_name="Cloudflare, Inc.",
        display_name="Cloudflare",
        cik="0001477333",
    )
    fastly = Company(
        legal_name="Fastly, Inc.",
        display_name="Fastly",
        cik="0001517413",
    )
    session.add_all([exchange, cloudflare, fastly])
    session.flush()
    session.add_all(
        [
            CompanyTicker(
                company_id=cloudflare.id,
                exchange_id=exchange.id,
                symbol="NET",
                is_primary=True,
            ),
            CompanyTicker(
                company_id=fastly.id,
                exchange_id=exchange.id,
                symbol="FSLY",
                is_primary=True,
            ),
            CompanyAlias(
                company_id=cloudflare.id,
                alias="Edge Cloud",
                kind=AliasKind.COMMON,
            ),
            CompanyAlias(
                company_id=fastly.id,
                alias="Edge Cloud",
                kind=AliasKind.COMMON,
            ),
        ]
    )
    _seed_company_document(
        session,
        company=cloudflare,
        stable_source_id="cloudflare-2025",
        accession="0001477333-26-000001",
        fiscal_year=2025,
        summary="Cloudflare provides a connectivity cloud and security platform.",
        section_summary="Security products and platform adoption support enterprise growth.",
        chunk_text="Cloudflare operates a security platform for enterprise customers.",
    )
    _seed_company_document(
        session,
        company=fastly,
        stable_source_id="fastly-2025",
        accession="0001517413-26-000001",
        fiscal_year=2025,
        summary="Fastly provides an edge cloud platform.",
        section_summary="Fastly discusses competition and platform execution risks.",
        chunk_text="Fastly faces competition in edge security and delivery services.",
    )
    session.add(
        FinancialFact(
            company_id=cloudflare.id,
            taxonomy="us-gaap",
            concept="RevenueFromContractWithCustomerExcludingAssessedTax",
            canonical_metric="revenue",
            metric_mapping_version="sec-company-facts.v1",
            label="Revenue",
            value=Decimal("1669500000"),
            unit="USD",
            period_start=date(2025, 1, 1),
            period_end=date(2025, 12, 31),
            fiscal_year=2025,
            fiscal_period="FY",
            period_type="annual",
            accession_number="0001477333-26-000001",
            dimensions={},
            source_url="https://example.com/cloudflare-2025",
            source_hash="fact-cloudflare-2025",
        )
    )
    session.commit()


def _seed_company_document(
    session: Session,
    *,
    company: Company,
    stable_source_id: str,
    accession: str,
    fiscal_year: int,
    summary: str,
    section_summary: str,
    chunk_text: str,
) -> None:
    document = SourceDocument(
        company_id=company.id,
        kind=DocumentKind.SEC_FILING,
        source_system="sec_edgar",
        stable_source_id=stable_source_id,
        source_url=f"https://example.com/{stable_source_id}",
        title=f"{company.display_name} 10-K",
        accession_number=accession,
        filing_form="10-K",
        period_end=date(fiscal_year, 12, 31),
        fiscal_year=fiscal_year,
        fiscal_period="FY",
        metadata_json={},
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_label=stable_source_id,
        content_hash=f"version-{stable_source_id}",
        source_hash=f"version-{stable_source_id}",
        state=DocumentVersionState.CURRENT,
        is_current=True,
        metadata_json={},
    )
    session.add(version)
    session.flush()
    section = FilingSection(
        document_version_id=version.id,
        section_code="business",
        title="Business",
        ordinal_path="1",
        heading_level=1,
        content_hash=f"section-{stable_source_id}",
    )
    session.add(section)
    session.flush()
    session.add_all(
        [
            DocumentSummary(
                document_version_id=version.id,
                summary_text=summary,
                model_name="test",
                content_hash=content_hash(summary),
                metadata_json={},
            ),
            SectionSummary(
                section_id=section.id,
                summary_text=section_summary,
                model_name="test",
                content_hash=content_hash(section_summary),
                metadata_json={},
            ),
            DocumentChunk(
                document_version_id=version.id,
                section_id=section.id,
                chunk_index=0,
                text=chunk_text,
                content_hash=content_hash(chunk_text),
                token_count=len(chunk_text.split()),
                metadata_json={},
            ),
        ]
    )
