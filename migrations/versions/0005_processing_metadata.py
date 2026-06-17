"""add processing metadata

Revision ID: 0005_processing_metadata
Revises: 0004_pdf_blocks
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_processing_metadata"
down_revision = "0004_pdf_blocks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata_column = postgresql.JSONB(astext_type=sa.Text())
    op.add_column(
        "document_summaries",
        sa.Column(
            "metadata_json",
            metadata_column,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "section_summaries",
        sa.Column(
            "metadata_json",
            metadata_column,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "document_chunks",
        sa.Column(
            "metadata_json",
            metadata_column,
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.alter_column("document_summaries", "metadata_json", server_default=None)
    op.alter_column("section_summaries", "metadata_json", server_default=None)
    op.alter_column("document_chunks", "metadata_json", server_default=None)


def downgrade() -> None:
    op.drop_column("document_chunks", "metadata_json")
    op.drop_column("section_summaries", "metadata_json")
    op.drop_column("document_summaries", "metadata_json")
