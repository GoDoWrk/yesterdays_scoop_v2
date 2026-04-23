"""add pipeline run history tables

Revision ID: 0015_pipeline_run_history
Revises: 0014_service_state_stage_timestamps
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0015_pipeline_run_history"
down_revision = "0014_service_state_stage_timestamps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pipeline_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_token", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="running"),
        sa.Column("ingested_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("clustered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summarized_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_clusters_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("indexed_articles_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stage_error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=True),
    )
    op.create_index("ix_pipeline_runs_run_token", "pipeline_runs", ["run_token"], unique=True)
    op.create_index("ix_pipeline_runs_started_at", "pipeline_runs", ["started_at"], unique=False)
    op.create_index("ix_pipeline_runs_finished_at", "pipeline_runs", ["finished_at"], unique=False)

    op.create_table(
        "pipeline_stage_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("pipeline_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="success"),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_pipeline_stage_events_run_id", "pipeline_stage_events", ["run_id"], unique=False)
    op.create_index("ix_pipeline_stage_events_stage", "pipeline_stage_events", ["stage"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pipeline_stage_events_stage", table_name="pipeline_stage_events")
    op.drop_index("ix_pipeline_stage_events_run_id", table_name="pipeline_stage_events")
    op.drop_table("pipeline_stage_events")

    op.drop_index("ix_pipeline_runs_finished_at", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_started_at", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_run_token", table_name="pipeline_runs")
    op.drop_table("pipeline_runs")
