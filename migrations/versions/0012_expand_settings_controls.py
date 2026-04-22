"""expand app settings controls for homepage, ranking, backup, and notifications

Revision ID: 0012_expand_settings_controls
Revises: 0011_setup_wizard_expansion
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_expand_settings_controls"
down_revision = "0011_setup_wizard_expansion"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("app_settings")}

    if "homepage_section_limit" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("homepage_section_limit", sa.Integer(), nullable=False, server_default="6"),
        )
    if "homepage_show_fast_moving" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("homepage_show_fast_moving", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if "homepage_show_recently_updated" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("homepage_show_recently_updated", sa.Boolean(), nullable=False, server_default=sa.true()),
        )
    if "ranking_impact_weight" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("ranking_impact_weight", sa.Float(), nullable=False, server_default="0.28"),
        )
    if "ranking_freshness_weight" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("ranking_freshness_weight", sa.Float(), nullable=False, server_default="0.20"),
        )
    if "confirmation_impact_threshold" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("confirmation_impact_threshold", sa.Float(), nullable=False, server_default="0.65"),
        )
    if "backup_schedule_enabled" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("backup_schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "backup_schedule_cron" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("backup_schedule_cron", sa.String(length=64), nullable=False, server_default="0 3 * * *"),
        )
    if "notifications_enabled" not in cols:
        op.add_column(
            "app_settings",
            sa.Column("notifications_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    op.drop_column("app_settings", "notifications_enabled")
    op.drop_column("app_settings", "backup_schedule_cron")
    op.drop_column("app_settings", "backup_schedule_enabled")
    op.drop_column("app_settings", "confirmation_impact_threshold")
    op.drop_column("app_settings", "ranking_freshness_weight")
    op.drop_column("app_settings", "ranking_impact_weight")
    op.drop_column("app_settings", "homepage_show_recently_updated")
    op.drop_column("app_settings", "homepage_show_fast_moving")
    op.drop_column("app_settings", "homepage_section_limit")
