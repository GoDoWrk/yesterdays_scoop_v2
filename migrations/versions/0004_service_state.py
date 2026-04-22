"""add service state table

Revision ID: 0004_service_state
Revises: 0003_miniflux_bootstrap_retry_state
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_service_state"
down_revision = "0003_miniflux_bootstrap_retry_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "service_state" in inspector.get_table_names():
        return

    op.create_table(
        "service_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scheduler_last_tick_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_pipeline_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_pipeline_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_pipeline_success", sa.Boolean(), nullable=True),
        sa.Column("last_pipeline_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("service_state")
