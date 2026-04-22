"""add miniflux bootstrap state columns

Revision ID: 0002_miniflux_bootstrap_state
Revises: 0001_baseline
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_miniflux_bootstrap_state"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("app_settings")}

    if "miniflux_api_key" not in columns:
        op.add_column("app_settings", sa.Column("miniflux_api_key", sa.String(length=255), nullable=True))
    if "miniflux_bootstrap_completed" not in columns:
        op.add_column("app_settings", sa.Column("miniflux_bootstrap_completed", sa.Boolean(), nullable=False, server_default=sa.false()))
    if "miniflux_bootstrap_error" not in columns:
        op.add_column("app_settings", sa.Column("miniflux_bootstrap_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_settings", "miniflux_bootstrap_error")
    op.drop_column("app_settings", "miniflux_bootstrap_completed")
    op.drop_column("app_settings", "miniflux_api_key")
