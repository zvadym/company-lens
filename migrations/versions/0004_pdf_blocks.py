"""add pdf blocks

Revision ID: 0004_pdf_blocks
Revises: 0003_sec_ingestion_failures
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_pdf_blocks"
down_revision = "0003_sec_ingestion_failures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pdf_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("page_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("text_hash", sa.String(length=128), nullable=True),
        sa.Column("x0_points", sa.Numeric(10, 2), nullable=True),
        sa.Column("y0_points", sa.Numeric(10, 2), nullable=True),
        sa.Column("x1_points", sa.Numeric(10, 2), nullable=True),
        sa.Column("y1_points", sa.Numeric(10, 2), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=True),
        sa.Column("char_end", sa.Integer(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["document_version_id"], ["document_versions.id"]),
        sa.ForeignKeyConstraint(["page_id"], ["pdf_pages.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("page_id", "block_index", name="uq_pdf_block_page_index"),
    )
    op.create_index(
        op.f("ix_pdf_blocks_document_version_id"),
        "pdf_blocks",
        ["document_version_id"],
        unique=False,
    )
    op.create_index(op.f("ix_pdf_blocks_page_id"), "pdf_blocks", ["page_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_pdf_blocks_page_id"), table_name="pdf_blocks")
    op.drop_index(op.f("ix_pdf_blocks_document_version_id"), table_name="pdf_blocks")
    op.drop_table("pdf_blocks")
