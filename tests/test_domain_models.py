from __future__ import annotations

from sqlalchemy import ForeignKeyConstraint, UniqueConstraint

from company_lens.db import models
from company_lens.db.base import Base
from company_lens.db.types import PgVector


def test_core_domain_tables_are_registered() -> None:
    expected_tables = {
        "companies",
        "company_aliases",
        "company_identifiers",
        "company_tickers",
        "exchanges",
        "source_documents",
        "document_versions",
        "document_summaries",
        "filing_sections",
        "section_summaries",
        "document_chunks",
        "chunk_embeddings",
        "embedding_indexes",
        "pdf_pages",
        "pdf_blocks",
        "source_artifacts",
        "financial_facts",
        "macro_observations",
        "ingestion_runs",
        "ingestion_failures",
        "evidence_records",
        "citation_records",
        "claim_records",
    }

    assert expected_tables.issubset(Base.metadata.tables)
    assert models.Company.__tablename__ == "companies"


def test_evidence_and_claim_records_support_stable_claim_level_citations() -> None:
    evidence = Base.metadata.tables["evidence_records"]
    claims = Base.metadata.tables["claim_records"]
    citations = Base.metadata.tables["citation_records"]

    assert "stable_id" in evidence.columns
    assert "metadata_json" in evidence.columns
    assert "lineage_json" in evidence.columns
    assert "run_id" in claims.columns
    assert "supported" in claims.columns
    assert citations.columns["claim_id"].foreign_keys


def test_chunk_embedding_vector_has_fixed_dimensions_for_hnsw() -> None:
    embedding_type = Base.metadata.tables["chunk_embeddings"].columns["embedding"].type

    assert isinstance(embedding_type, PgVector)
    assert embedding_type.dimensions == 384
    assert embedding_type.get_col_spec() == "vector(384)"


def test_chunk_preserves_section_and_document_lineage() -> None:
    chunk = Base.metadata.tables["document_chunks"]
    foreign_key_targets = {
        element.target_fullname
        for constraint in chunk.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        for element in constraint.elements
    }

    assert "document_versions.id" in foreign_key_targets
    assert "filing_sections.id" in foreign_key_targets


def test_pdf_block_preserves_page_and_document_lineage() -> None:
    block = Base.metadata.tables["pdf_blocks"]
    foreign_key_targets = {
        element.target_fullname
        for constraint in block.constraints
        if isinstance(constraint, ForeignKeyConstraint)
        for element in constraint.elements
    }
    unique_constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in block.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert "document_versions.id" in foreign_key_targets
    assert "pdf_pages.id" in foreign_key_targets
    assert ("page_id", "block_index") in unique_constraints
    assert "x0_points" in block.columns
    assert "metadata_json" in block.columns


def test_structured_facts_are_separate_from_chunks() -> None:
    facts = Base.metadata.tables["financial_facts"]
    chunks = Base.metadata.tables["document_chunks"]

    assert "value" in facts.columns
    assert "unit" in facts.columns
    assert "period_end" in facts.columns
    assert "canonical_metric" in facts.columns
    assert "metric_mapping_version" in facts.columns
    assert "period_type" in facts.columns
    assert "filed_date" in facts.columns
    assert "form" in facts.columns
    assert "text" not in facts.columns
    assert "value" not in chunks.columns
