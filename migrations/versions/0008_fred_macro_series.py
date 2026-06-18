"""add FRED macro series metadata and revision-aware observations

Revision ID: 0008_fred_macro_series
Revises: 0007_company_facts_metrics
Create Date: 2026-06-18
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_fred_macro_series"
down_revision = "0007_company_facts_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "macro_series",
        sa.Column("series_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("frequency", sa.String(length=128), nullable=False),
        sa.Column("frequency_short", sa.String(length=32), nullable=False),
        sa.Column("units", sa.String(length=128), nullable=False),
        sa.Column("units_short", sa.String(length=64), nullable=False),
        sa.Column("seasonal_adjustment", sa.String(length=255), nullable=False),
        sa.Column("seasonal_adjustment_short", sa.String(length=64), nullable=False),
        sa.Column("observation_start", sa.Date(), nullable=False),
        sa.Column("observation_end", sa.Date(), nullable=False),
        sa.Column("last_updated_at_source", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("series_id"),
    )

    # Preserve legacy observations before adding the metadata foreign key.
    op.execute(
        "INSERT INTO macro_series "
        "(series_id, title, frequency, frequency_short, units, units_short, "
        "seasonal_adjustment, seasonal_adjustment_short, observation_start, observation_end, "
        "source_url) "
        "SELECT series_id, series_id, 'Unknown', 'NA', MIN(unit), MIN(unit), 'Unknown', 'NA', "
        "MIN(observed_at), MAX(observed_at), MIN(source_url) "
        "FROM macro_observations GROUP BY series_id"
    )
    op.drop_constraint("uq_macro_observation_vintage", "macro_observations", type_="unique")
    op.add_column("macro_observations", sa.Column("realtime_start", sa.Date(), nullable=True))
    op.add_column("macro_observations", sa.Column("realtime_end", sa.Date(), nullable=True))
    op.add_column(
        "macro_observations", sa.Column("raw_value", sa.String(length=128), nullable=True)
    )
    op.add_column(
        "macro_observations",
        sa.Column("is_missing", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("macro_observations", sa.Column("frequency", sa.String(length=32), nullable=True))
    op.execute(
        "UPDATE macro_observations SET "
        "realtime_start = COALESCE(vintage_date, observed_at), "
        "realtime_end = COALESCE(vintage_date, observed_at), "
        "raw_value = value::text, frequency = 'NA'"
    )
    for column in ("realtime_start", "realtime_end", "raw_value", "frequency"):
        op.alter_column("macro_observations", column, nullable=False)
    op.alter_column(
        "macro_observations",
        "value",
        existing_type=sa.Numeric(precision=28, scale=6),
        type_=sa.Numeric(precision=38, scale=12),
        nullable=True,
    )
    op.create_foreign_key(
        "fk_macro_observations_series_id",
        "macro_observations",
        "macro_series",
        ["series_id"],
        ["series_id"],
    )
    op.create_unique_constraint(
        "uq_macro_observation_vintage",
        "macro_observations",
        ["series_id", "observed_at", "realtime_start", "realtime_end"],
    )
    op.create_index(
        "ix_macro_observations_series_date",
        "macro_observations",
        ["series_id", "observed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_macro_observations_series_date", table_name="macro_observations")
    op.drop_constraint("uq_macro_observation_vintage", "macro_observations", type_="unique")
    op.drop_constraint("fk_macro_observations_series_id", "macro_observations", type_="foreignkey")
    op.execute("DELETE FROM macro_observations WHERE value IS NULL")
    op.alter_column(
        "macro_observations",
        "value",
        existing_type=sa.Numeric(precision=38, scale=12),
        type_=sa.Numeric(precision=28, scale=6),
        nullable=False,
    )
    for column in ("frequency", "is_missing", "raw_value", "realtime_end", "realtime_start"):
        op.drop_column("macro_observations", column)
    op.create_unique_constraint(
        "uq_macro_observation_vintage",
        "macro_observations",
        ["series_id", "observed_at", "vintage_date"],
    )
    op.drop_table("macro_series")
