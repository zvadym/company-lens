"""add stable evidence and claim-level citation records

Revision ID: 0010_evidence_claim_validation
Revises: 0009_research_sessions
Create Date: 2026-06-21
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0010_evidence_claim_validation"
down_revision = "0009_research_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE evidence_kind ADD VALUE IF NOT EXISTS 'CALCULATION'")
    op.add_column("evidence_records", sa.Column("stable_id", sa.String(255), nullable=True))
    op.add_column("evidence_records", sa.Column("summary", sa.Text(), nullable=True))
    op.add_column(
        "evidence_records",
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "evidence_records",
        sa.Column(
            "lineage_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        "UPDATE evidence_records SET stable_id = lower(kind::text) || ':' || source_id "
        "WHERE stable_id IS NULL"
    )
    op.alter_column("evidence_records", "stable_id", nullable=False)
    op.create_unique_constraint("uq_evidence_record_stable_id", "evidence_records", ["stable_id"])

    op.create_table(
        "claim_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_key", sa.String(255), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("material", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("supported", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column(
            "validation_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "claim_key", name="uq_claim_run_key"),
    )
    op.create_index("ix_claim_records_run_id", "claim_records", ["run_id"], unique=False)
    op.add_column(
        "citation_records",
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_citation_records_claim_id",
        "citation_records",
        "claim_records",
        ["claim_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_citation_records_claim_id", "citation_records", type_="foreignkey")
    op.drop_column("citation_records", "claim_id")
    op.drop_index("ix_claim_records_run_id", table_name="claim_records")
    op.drop_table("claim_records")
    op.drop_constraint("uq_evidence_record_stable_id", "evidence_records", type_="unique")
    op.drop_column("evidence_records", "lineage_json")
    op.drop_column("evidence_records", "metadata_json")
    op.drop_column("evidence_records", "summary")
    op.drop_column("evidence_records", "stable_id")
    # PostgreSQL enum values are intentionally retained during downgrade.
