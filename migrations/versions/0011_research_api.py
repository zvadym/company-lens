"""add durable research API runs, events, feedback, and rate limits

Revision ID: 0011_research_api
Revises: 0010_evidence_claim_validation
Create Date: 2026-06-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0011_research_api"
down_revision = "0010_evidence_claim_validation"
branch_labels = None
depends_on = None

ACTIVE_STATUSES = "'queued', 'running', 'cancellation_requested'"


def upgrade() -> None:
    op.create_table(
        "research_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", sa.String(length=128), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column(
            "policy_json", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result_json", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(length=128), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "queued_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cancellation_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("worker_lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_runs_session_id", "research_runs", ["session_id"])
    op.create_index("ix_research_runs_status", "research_runs", ["status"])
    op.create_index(
        "uq_research_runs_active_session",
        "research_runs",
        ["session_id"],
        unique=True,
        postgresql_where=sa.text(f"status IN ({ACTIVE_STATUSES})"),
    )
    op.create_table(
        "research_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("schema_version", sa.String(length=16), server_default="1", nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "event_key", name="uq_research_event_key"),
    )
    op.create_index("ix_research_events_run_id", "research_events", ["run_id"])
    op.create_table(
        "research_feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("rating", sa.String(length=16), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("actor_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(["run_id"], ["research_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_research_feedback_run_id", "research_feedback", ["run_id"])
    op.create_table(
        "rate_limit_buckets",
        sa.Column("bucket_key", sa.String(length=128), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("bucket_key", "window_started_at"),
    )
    op.create_index("ix_rate_limit_buckets_expires_at", "rate_limit_buckets", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_rate_limit_buckets_expires_at", table_name="rate_limit_buckets")
    op.drop_table("rate_limit_buckets")
    op.drop_index("ix_research_feedback_run_id", table_name="research_feedback")
    op.drop_table("research_feedback")
    op.drop_index("ix_research_events_run_id", table_name="research_events")
    op.drop_table("research_events")
    op.drop_index("uq_research_runs_active_session", table_name="research_runs")
    op.drop_index("ix_research_runs_status", table_name="research_runs")
    op.drop_index("ix_research_runs_session_id", table_name="research_runs")
    op.drop_table("research_runs")
