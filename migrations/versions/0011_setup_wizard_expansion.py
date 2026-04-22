"""expand setup wizard state and relevance preference

Revision ID: 0011_setup_wizard_expansion
Revises: 0010_social_context
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_setup_wizard_expansion"
down_revision = "0010_social_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("app_settings")}

    if "local_relevance_preference" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("local_relevance_preference", sa.String(length=32), nullable=False, server_default="medium"),
        )
    if "setup_last_step" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("setup_last_step", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    op.drop_column("app_settings", "setup_last_step")
    op.drop_column("app_settings", "local_relevance_preference")
