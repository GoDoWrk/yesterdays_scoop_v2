"""add ai fallback setting flag

Revision ID: 0007_ai_fallback_setting
Revises: 0006_setup_wizard_settings
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_ai_fallback_setting"
down_revision = "0006_setup_wizard_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("app_settings")}
    if "openai_fallback_enabled" not in columns:
        op.add_column(
            "app_settings",
            sa.Column("openai_fallback_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    op.drop_column("app_settings", "openai_fallback_enabled")
