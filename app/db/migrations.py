import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.db.base import Base
from app.db.session import engine
import app.models.models  # noqa: F401 - ensure model metadata is registered

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    root = Path(__file__).resolve().parents[2]
    alembic_ini = root / "alembic.ini"
    script_locations = [root / "alembic", root / "migrations"]
    script_location = next((path for path in script_locations if path.exists()), None)

    if not alembic_ini.exists() or not script_location:
        missing_parts = []
        if not alembic_ini.exists():
            missing_parts.append(f"config={alembic_ini}")
        if not script_location:
            missing_parts.append("script_location=(/app/alembic or /app/migrations)")
        logger.warning(
            "Alembic assets are missing (%s). Falling back to SQLAlchemy metadata.create_all().",
            ", ".join(missing_parts),
        )
        Base.metadata.create_all(bind=engine)
        return

    try:
        cfg = Config(str(alembic_ini))
        cfg.set_main_option("script_location", str(script_location))
        command.upgrade(cfg, "head")
        logger.info("Database migrations applied from %s.", script_location)
    except Exception as exc:
        logger.exception(
            "Alembic migration failed (%s). Falling back to SQLAlchemy metadata.create_all().",
            exc,
        )
        Base.metadata.create_all(bind=engine)
        logger.warning("Schema fallback completed with SQLAlchemy metadata.create_all().")
