"""add cluster importance and lifecycle fields

Revision ID: 0008_cluster_importance_fields
Revises: 0007_ai_fallback_setting
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_cluster_importance_fields"
down_revision = "0007_ai_fallback_setting"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("clusters")}

    additions = [
        ("impact_score", sa.Float(), sa.text("0")),
        ("local_relevance_score", sa.Float(), sa.text("0")),
        ("source_confidence_score", sa.Float(), sa.text("0")),
        ("corroboration_count", sa.Integer(), sa.text("0")),
        ("velocity_score", sa.Float(), sa.text("0")),
        ("freshness_score", sa.Float(), sa.text("0")),
        ("staleness_decay", sa.Float(), sa.text("1")),
        ("importance_score", sa.Float(), sa.text("0")),
        ("cluster_state", sa.String(length=32), sa.text("'emerging'")),
        ("last_activity_at", sa.DateTime(timezone=True), None),
    ]

    for name, type_, default in additions:
        if name not in columns:
            op.add_column(
                "clusters",
                sa.Column(name, type_, nullable=True if name == "last_activity_at" else False, server_default=default),
            )


def downgrade() -> None:
    for name in [
        "last_activity_at",
        "cluster_state",
        "importance_score",
        "staleness_decay",
        "freshness_score",
        "velocity_score",
        "corroboration_count",
        "source_confidence_score",
        "local_relevance_score",
        "impact_score",
    ]:
        op.drop_column("clusters", name)
