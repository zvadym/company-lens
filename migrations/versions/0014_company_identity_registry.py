"""add global company identity registry

Revision ID: 0014_company_identity_registry
Revises: 0013_research_correlation
Create Date: 2026-06-24
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0014_company_identity_registry"
down_revision = "0013_research_correlation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cik", sa.String(length=10), nullable=True),
        sa.Column("legal_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_legal_name", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_display_name", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "source_metadata",
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
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", name="uq_company_identity_company_id"),
        sa.UniqueConstraint("cik", name="uq_company_identity_cik"),
    )
    op.create_index(
        "ix_company_identities_normalized_display_name",
        "company_identities",
        ["normalized_display_name"],
    )
    op.create_index(
        "ix_company_identities_normalized_legal_name",
        "company_identities",
        ["normalized_legal_name"],
    )

    op.create_table(
        "company_identity_tickers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("normalized_symbol", sa.String(length=32), nullable=False),
        sa.Column("exchange_code", sa.String(length=32), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_to", sa.Date(), nullable=True),
        sa.Column(
            "source_metadata",
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
        sa.ForeignKeyConstraint(["identity_id"], ["company_identities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "identity_id",
            "normalized_symbol",
            "source",
            "valid_from",
            name="uq_company_identity_ticker_source_period",
        ),
    )
    op.create_index(
        "ix_company_identity_tickers_normalized_symbol",
        "company_identity_tickers",
        ["normalized_symbol"],
    )

    op.create_table(
        "company_identity_aliases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("identity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("alias", sa.String(length=255), nullable=False),
        sa.Column("normalized_alias", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "source_metadata",
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
        sa.ForeignKeyConstraint(["identity_id"], ["company_identities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "identity_id",
            "normalized_alias",
            "kind",
            "source",
            name="uq_company_identity_alias_kind_source",
        ),
    )
    op.create_index(
        "ix_company_identity_aliases_normalized_alias",
        "company_identity_aliases",
        ["normalized_alias"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_company_identity_aliases_normalized_alias",
        table_name="company_identity_aliases",
    )
    op.drop_table("company_identity_aliases")
    op.drop_index(
        "ix_company_identity_tickers_normalized_symbol",
        table_name="company_identity_tickers",
    )
    op.drop_table("company_identity_tickers")
    op.drop_index(
        "ix_company_identities_normalized_legal_name",
        table_name="company_identities",
    )
    op.drop_index(
        "ix_company_identities_normalized_display_name",
        table_name="company_identities",
    )
    op.drop_table("company_identities")
