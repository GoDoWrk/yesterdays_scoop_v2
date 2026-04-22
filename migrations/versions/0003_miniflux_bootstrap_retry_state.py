"""add miniflux bootstrap retry tracking

Revision ID: 0003_miniflux_bootstrap_retry_state
Revises: 0002_miniflux_bootstrap_state
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_miniflux_bootstrap_retry_state"
down_revision = "0002_miniflux_bootstrap_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("app_settings")}

    if "miniflux_last_attempt_at" not in columns:
        op.add_column("app_settings", sa.Column("miniflux_last_attempt_at", sa.DateTime(timezone=True), nullable=True))
    if "miniflux_retry_count" not in columns:
        op.add_column("app_settings", sa.Column("miniflux_retry_count", sa.Integer(), nullable=False, server_default="0"))


def downgrade() -> None:
    op.drop_column("app_settings", "miniflux_retry_count")
    op.drop_column("app_settings", "miniflux_last_attempt_at")
