"""add sec ingestion failure tracking

Revision ID: 0003_sec_ingestion_failures
Revises: 0002_core_domain_model
Create Date: 2026-06-16
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003_sec_ingestion_failures"
down_revision = "0002_core_domain_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingestion_failures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage", sa.String(length=128), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("retryable", sa.Boolean(), nullable=False),
        sa.Column("details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["ingestion_runs.id"]),
        sa.ForeignKeyConstraint(["source_document_id"], ["source_documents.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ingestion_failures_company_id"),
        "ingestion_failures",
        ["company_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingestion_failures_run_id"),
        "ingestion_failures",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingestion_failures_source_document_id"),
        "ingestion_failures",
        ["source_document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ingestion_failures_stage"),
        "ingestion_failures",
        ["stage"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ingestion_failures_stage"), table_name="ingestion_failures")
    op.drop_index(op.f("ix_ingestion_failures_source_document_id"), table_name="ingestion_failures")
    op.drop_index(op.f("ix_ingestion_failures_run_id"), table_name="ingestion_failures")
    op.drop_index(op.f("ix_ingestion_failures_company_id"), table_name="ingestion_failures")
    op.drop_table("ingestion_failures")
