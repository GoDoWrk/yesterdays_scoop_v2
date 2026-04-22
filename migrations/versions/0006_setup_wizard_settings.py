"""add setup wizard runtime config fields

Revision ID: 0006_setup_wizard_settings
Revises: 0005_service_state_heartbeat_fields
Create Date: 2026-04-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_setup_wizard_settings"
down_revision = "0005_service_state_heartbeat_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("app_settings")}

    additions = [
        ("miniflux_base_url", sa.String(length=255)),
        ("miniflux_admin_username", sa.String(length=128)),
        ("miniflux_admin_password", sa.String(length=255)),
        ("source_preset", sa.String(length=32)),
        ("meili_url", sa.String(length=255)),
        ("meili_master_key", sa.String(length=255)),
        ("ollama_base_url", sa.String(length=255)),
        ("ollama_chat_model", sa.String(length=128)),
        ("ollama_embed_model", sa.String(length=128)),
        ("openai_model", sa.String(length=128)),
        ("setup_completed", sa.Boolean()),
    ]

    for name, typ in additions:
        if name not in columns:
            nullable = True if name not in {"source_preset", "setup_completed"} else False
            server_default = sa.text("'standard'") if name == "source_preset" else (sa.false() if name == "setup_completed" else None)
            op.add_column("app_settings", sa.Column(name, typ, nullable=nullable, server_default=server_default))


def downgrade() -> None:
    for name in [
        "setup_completed",
        "openai_model",
        "ollama_embed_model",
        "ollama_chat_model",
        "ollama_base_url",
        "meili_master_key",
        "meili_url",
        "source_preset",
        "miniflux_admin_password",
        "miniflux_admin_username",
        "miniflux_base_url",
    ]:
        op.drop_column("app_settings", name)
