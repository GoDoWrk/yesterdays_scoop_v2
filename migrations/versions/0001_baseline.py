"""baseline

Revision ID: 0001_baseline
Revises: 
Create Date: 2026-04-21
"""

from alembic import op
from app.db.base import Base
from app.models import *  # noqa: F401,F403

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
