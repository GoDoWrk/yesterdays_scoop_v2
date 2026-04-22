"""extend service state heartbeat and pipeline stage fields

Revision ID: 0005_service_state_heartbeat_fields
Revises: 0004_service_state
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_service_state_heartbeat_fields"
down_revision = "0004_service_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("service_state")}

    if "worker_last_heartbeat_at" not in columns:
        op.add_column("service_state", sa.Column("worker_last_heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    if "last_pipeline_stage" not in columns:
        op.add_column("service_state", sa.Column("last_pipeline_stage", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("service_state", "last_pipeline_stage")
    op.drop_column("service_state", "worker_last_heartbeat_at")
