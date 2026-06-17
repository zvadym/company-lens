"""add retrieval indexes

Revision ID: 0006_retrieval_indexes
Revises: 0005_processing_metadata
Create Date: 2026-06-17
"""

from __future__ import annotations

from alembic import op

revision = "0006_retrieval_indexes"
down_revision = "0005_processing_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE document_chunks
        ADD COLUMN IF NOT EXISTS search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('english', coalesce(text, ''))) STORED
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_search_vector "
        "ON document_chunks USING gin (search_vector)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_embedding_hnsw "
        "ON chunk_embeddings USING hnsw (embedding vector_cosine_ops)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_index_hash "
        "ON chunk_embeddings (embedding_index_id, content_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_document_version "
        "ON document_chunks (document_version_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_section ON document_chunks (section_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_filing_sections_section_code "
        "ON filing_sections (section_code)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_source_documents_retrieval_filters "
        "ON source_documents (company_id, kind, filing_form, filing_date, period_end)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_source_documents_period "
        "ON source_documents (fiscal_year, fiscal_period)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_source_documents_source_system "
        "ON source_documents (source_system)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_source_documents_source_system")
    op.execute("DROP INDEX IF EXISTS ix_source_documents_period")
    op.execute("DROP INDEX IF EXISTS ix_source_documents_retrieval_filters")
    op.execute("DROP INDEX IF EXISTS ix_filing_sections_section_code")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_section")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_document_version")
    op.execute("DROP INDEX IF EXISTS ix_chunk_embeddings_index_hash")
    op.execute("DROP INDEX IF EXISTS ix_chunk_embeddings_embedding_hnsw")
    op.execute("DROP INDEX IF EXISTS ix_document_chunks_search_vector")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS search_vector")
