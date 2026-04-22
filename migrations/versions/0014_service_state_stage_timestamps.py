"""add per-stage pipeline timestamps to service_state

Revision ID: 0014_service_state_stage_timestamps
Revises: 0013_source_metadata_fields
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0014_service_state_stage_timestamps"
down_revision = "0013_source_metadata_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("service_state", sa.Column("last_ingest_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("service_state", sa.Column("last_clustering_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("service_state", sa.Column("last_summarization_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("service_state", sa.Column("last_ranking_run_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("service_state", "last_ranking_run_at")
    op.drop_column("service_state", "last_summarization_run_at")
    op.drop_column("service_state", "last_clustering_run_at")
    op.drop_column("service_state", "last_ingest_run_at")
