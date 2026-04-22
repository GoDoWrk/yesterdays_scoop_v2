"""add source metadata fields

Revision ID: 0013_source_metadata_fields
Revises: 0012_expand_settings_controls
Create Date: 2026-04-22
"""

from alembic import op
import sqlalchemy as sa


revision = "0013_source_metadata_fields"
down_revision = "0012_expand_settings_controls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("source_type", sa.String(length=32), nullable=True))
    op.add_column("sources", sa.Column("topic", sa.String(length=64), nullable=True))
    op.add_column("sources", sa.Column("geography", sa.String(length=64), nullable=True))

    op.execute("UPDATE sources SET source_type='major_outlet' WHERE source_type IS NULL")
    op.execute("UPDATE sources SET topic='general' WHERE topic IS NULL")
    op.execute("UPDATE sources SET geography=COALESCE(region,'global') WHERE geography IS NULL")

    op.alter_column("sources", "source_type", nullable=False)
    op.alter_column("sources", "topic", nullable=False)
    op.alter_column("sources", "geography", nullable=False)


def downgrade() -> None:
    op.drop_column("sources", "geography")
    op.drop_column("sources", "topic")
    op.drop_column("sources", "source_type")
