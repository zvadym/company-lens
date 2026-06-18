from __future__ import annotations

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from company_lens.db.models import (
    ChunkEmbedding,
    Company,
    DocumentChunk,
    DocumentKind,
    DocumentVersion,
    DocumentVersionState,
    EmbeddingIndex,
    FilingSection,
    SourceDocument,
)
from company_lens.db.session import build_session_factory
from company_lens.processing.text import content_hash
from company_lens.retrieval.indexing import EmbeddingIndexingService
from company_lens.retrieval.schemas import EmbeddingIndexingRequest, RetrievalRequest
from company_lens.retrieval.service import RetrievalService

pytestmark = pytest.mark.skipif(
    not os.getenv("COMPANY_LENS_TEST_DATABASE_URL"),
    reason="COMPANY_LENS_TEST_DATABASE_URL is not set.",
)


def test_postgres_fts_pgvector_and_retrieval_indexes(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.environ["COMPANY_LENS_TEST_DATABASE_URL"]
    monkeypatch.setenv("COMPANY_LENS_DATABASE_URL", database_url)
    command.upgrade(Config("alembic.ini"), "head")

    session_factory = build_session_factory(database_url)
    with session_factory() as session:
        _clear_retrieval_tables(session)
        _seed_postgres_corpus(session)
        indexing = EmbeddingIndexingService(session=session).index_chunks(
            EmbeddingIndexingRequest()
        )
        dense = RetrievalService(session=session).retrieve(
            RetrievalRequest(query="connectivity security platform", mode="dense")
        )
        lexical = RetrievalService(session=session).retrieve(
            RetrievalRequest(query="competition security vendors", mode="lexical")
        )
        hybrid = RetrievalService(session=session).retrieve(
            RetrievalRequest(query="enterprise security platform", mode="hybrid")
        )
        search_vector_exists = session.execute(
            text(
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'document_chunks'
                  AND column_name = 'search_vector'
                """
            )
        ).first()

    assert indexing.indexed == 3
    assert dense.results
    assert dense.results[0].scores.vector_score is not None
    assert lexical.results
    assert lexical.results[0].scores.lexical_score is not None
    assert hybrid.results
    assert hybrid.results[0].scores.hybrid_score is not None
    assert search_vector_exists is not None


def _clear_retrieval_tables(session: Session) -> None:
    for model in (
        ChunkEmbedding,
        EmbeddingIndex,
        DocumentChunk,
        FilingSection,
        DocumentVersion,
        SourceDocument,
        Company,
    ):
        session.execute(delete(model))
    session.commit()


def _seed_postgres_corpus(session: Session) -> None:
    company = Company(
        legal_name="Cloudflare, Inc.",
        display_name="Cloudflare",
        cik="0001477333",
    )
    session.add(company)
    session.flush()
    document = SourceDocument(
        company_id=company.id,
        kind=DocumentKind.SEC_FILING,
        source_system="sec_edgar",
        stable_source_id="postgres-retrieval-demo",
        source_url="https://example.com/form10k.htm",
        title="Cloudflare 10-K",
        filing_form="10-K",
        fiscal_year=2025,
        fiscal_period="FY",
        metadata_json={},
    )
    session.add(document)
    session.flush()
    version = DocumentVersion(
        document_id=document.id,
        version_label="postgres-retrieval-demo",
        content_hash="version-hash",
        source_hash="version-hash",
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
        content_hash="section-hash",
    )
    session.add(section)
    session.flush()
    for index, chunk_text in enumerate(
        (
            "Cloudflare operates a connectivity cloud security platform.",
            "Enterprise customers expanded platform usage.",
            "Competition from security vendors remains meaningful.",
        )
    ):
        session.add(
            DocumentChunk(
                document_version_id=version.id,
                section_id=section.id,
                chunk_index=index,
                text=chunk_text,
                content_hash=content_hash(chunk_text),
                token_count=len(chunk_text.split()),
                metadata_json={},
            )
        )
    session.commit()
