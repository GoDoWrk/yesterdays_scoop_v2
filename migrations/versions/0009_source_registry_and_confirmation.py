"""add source registry and seeking confirmation fields

Revision ID: 0009_source_registry_and_confirmation
Revises: 0008_cluster_importance_fields
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0009_source_registry_and_confirmation"
down_revision = "0008_cluster_importance_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    source_cols = {c["name"] for c in inspector.get_columns("sources")}
    additions = [
        ("miniflux_feed_id", sa.Integer(), None, True),
        ("source_tier", sa.Integer(), sa.text("3"), False),
        ("priority_weight", sa.Float(), sa.text("1"), False),
        ("poll_frequency_minutes", sa.Integer(), sa.text("30"), False),
        ("health_status", sa.String(length=32), sa.text("'unknown'"), False),
        ("failure_count", sa.Integer(), sa.text("0"), False),
        ("average_latency_ms", sa.Float(), sa.text("0"), False),
        ("last_successful_fetch", sa.DateTime(timezone=True), None, True),
        ("last_attempted_fetch", sa.DateTime(timezone=True), None, True),
        ("last_article_time", sa.DateTime(timezone=True), None, True),
        ("outlet_family", sa.String(length=128), None, True),
    ]
    for name, typ, default, nullable in additions:
        if name not in source_cols:
            op.add_column("sources", sa.Column(name, typ, nullable=nullable, server_default=default))

    indexes = {ix["name"] for ix in inspector.get_indexes("sources")}
    if "ix_sources_miniflux_feed_id" not in indexes:
        op.create_index("ix_sources_miniflux_feed_id", "sources", ["miniflux_feed_id"], unique=True)

    cluster_cols = {c["name"] for c in inspector.get_columns("clusters")}
    if "seeking_confirmation" not in cluster_cols:
        op.add_column("clusters", sa.Column("seeking_confirmation", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for col in [
        "seeking_confirmation",
    ]:
        op.drop_column("clusters", col)

    op.drop_index("ix_sources_miniflux_feed_id", table_name="sources")
    for col in [
        "outlet_family",
        "last_article_time",
        "last_attempted_fetch",
        "last_successful_fetch",
        "average_latency_ms",
        "failure_count",
        "health_status",
        "poll_frequency_minutes",
        "priority_weight",
        "source_tier",
        "miniflux_feed_id",
    ]:
        op.drop_column("sources", col)
