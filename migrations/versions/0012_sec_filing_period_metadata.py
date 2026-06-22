"""backfill SEC filing reporting-period metadata

Revision ID: 0012_sec_filing_period_metadata
Revises: 0011_research_api
Create Date: 2026-06-22
"""

from __future__ import annotations

from alembic import op

revision = "0012_sec_filing_period_metadata"
down_revision = "0011_research_api"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE source_documents
        SET
            period_end = COALESCE(period_end, report_date),
            fiscal_year = COALESCE(fiscal_year, EXTRACT(YEAR FROM report_date)::integer),
            fiscal_period = COALESCE(
                fiscal_period,
                CASE
                    WHEN UPPER(REPLACE(filing_form, '/A', '')) IN ('10-K', '20-F', '40-F')
                    THEN 'FY'
                    ELSE NULL
                END
            )
        WHERE source_system = 'sec_edgar'
          AND report_date IS NOT NULL
        """
    )


def downgrade() -> None:
    # The source metadata remains valid independently of this migration.
    pass
