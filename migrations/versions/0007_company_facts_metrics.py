"""normalise SEC company facts

Revision ID: 0007_company_facts_metrics
Revises: 0006_retrieval_indexes
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0007_company_facts_metrics"
down_revision = "0006_retrieval_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "financial_facts",
        sa.Column("ingestion_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "financial_facts",
        sa.Column("canonical_metric", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "financial_facts",
        sa.Column("metric_mapping_version", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "financial_facts",
        sa.Column("period_type", sa.String(length=32), nullable=True),
    )
    op.add_column("financial_facts", sa.Column("form", sa.String(length=32), nullable=True))
    op.add_column("financial_facts", sa.Column("filed_date", sa.Date(), nullable=True))
    op.add_column("financial_facts", sa.Column("frame", sa.String(length=64), nullable=True))
    op.add_column(
        "financial_facts",
        sa.Column("is_amendment", sa.Boolean(), server_default=sa.false(), nullable=False),
    )

    # Existing rows predate canonical ingestion. Preserve them with an explicit legacy marker.
    op.execute(
        "UPDATE financial_facts "
        "SET canonical_metric = concept, metric_mapping_version = 'legacy', "
        "period_type = CASE WHEN period_start IS NULL THEN 'instant' ELSE 'other' END"
    )
    op.alter_column("financial_facts", "canonical_metric", nullable=False)
    op.alter_column("financial_facts", "metric_mapping_version", nullable=False)
    op.alter_column("financial_facts", "period_type", nullable=False)

    # The pre-ingestion schema did not enforce source-hash uniqueness. Exact duplicate rows
    # carry no additional provenance, so retain one before adding the idempotency constraint.
    op.execute(
        "DELETE FROM financial_facts AS duplicate USING financial_facts AS retained "
        "WHERE duplicate.source_hash = retained.source_hash "
        "AND duplicate.id::text > retained.id::text"
    )
    op.create_foreign_key(
        "fk_financial_facts_ingestion_run_id",
        "financial_facts",
        "ingestion_runs",
        ["ingestion_run_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_financial_fact_source_hash",
        "financial_facts",
        ["source_hash"],
    )
    op.create_index(
        "ix_financial_facts_metric_period",
        "financial_facts",
        ["company_id", "canonical_metric", "period_end"],
    )


def downgrade() -> None:
    op.drop_index("ix_financial_facts_metric_period", table_name="financial_facts")
    op.drop_constraint("uq_financial_fact_source_hash", "financial_facts", type_="unique")
    op.drop_constraint(
        "fk_financial_facts_ingestion_run_id",
        "financial_facts",
        type_="foreignkey",
    )
    for column in (
        "is_amendment",
        "frame",
        "filed_date",
        "form",
        "period_type",
        "metric_mapping_version",
        "canonical_metric",
        "ingestion_run_id",
    ):
        op.drop_column("financial_facts", column)
