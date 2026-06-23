"""persist API correlation IDs on research runs

Revision ID: 0013_research_correlation
Revises: 0012_sec_filing_period_metadata
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_research_correlation"
down_revision = "0012_sec_filing_period_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("research_runs", sa.Column("correlation_id", sa.String(128), nullable=True))
    op.create_index("ix_research_runs_correlation_id", "research_runs", ["correlation_id"])


def downgrade() -> None:
    op.drop_index("ix_research_runs_correlation_id", table_name="research_runs")
    op.drop_column("research_runs", "correlation_id")
