"""add social context table and settings

Revision ID: 0010_social_context
Revises: 0009_source_registry_and_confirmation
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0010_social_context"
down_revision = "0009_source_registry_and_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    tables = set(inspector.get_table_names())
    if "social_items" not in tables:
        op.create_table(
            "social_items",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("cluster_id", sa.Integer(), sa.ForeignKey("clusters.id", ondelete="CASCADE"), nullable=False),
            sa.Column("platform", sa.String(length=16), nullable=False),
            sa.Column("author", sa.String(length=255), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("url", sa.String(length=1024), nullable=False, unique=True),
            sa.Column("engagement", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("is_verified_source", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_social_items_cluster_id", "social_items", ["cluster_id"], unique=False)
        op.create_index("ix_social_items_platform", "social_items", ["platform"], unique=False)
        op.create_index("ix_social_items_created_at", "social_items", ["created_at"], unique=False)

    app_cols = {c["name"] for c in inspector.get_columns("app_settings")}
    additions = [
        ("enable_social_context", sa.Boolean(), sa.false()),
        ("enable_reddit_context", sa.Boolean(), sa.true()),
        ("enable_x_context", sa.Boolean(), sa.false()),
        ("social_max_items", sa.Integer(), sa.text("8")),
        ("x_api_bearer_token", sa.String(length=255), None),
    ]
    for name, typ, default in additions:
        if name not in app_cols:
            op.add_column("app_settings", sa.Column(name, typ, nullable=True if name == "x_api_bearer_token" else False, server_default=default))


def downgrade() -> None:
    for col in ["x_api_bearer_token", "social_max_items", "enable_x_context", "enable_reddit_context", "enable_social_context"]:
        op.drop_column("app_settings", col)

    op.drop_index("ix_social_items_created_at", table_name="social_items")
    op.drop_index("ix_social_items_platform", table_name="social_items")
    op.drop_index("ix_social_items_cluster_id", table_name="social_items")
    op.drop_table("social_items")
