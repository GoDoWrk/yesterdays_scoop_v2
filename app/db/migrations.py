import logging
from pathlib import Path

from alembic import command
from alembic.config import Config

logger = logging.getLogger(__name__)


def run_migrations() -> None:
    root = Path(__file__).resolve().parents[2]
    alembic_ini = root / "alembic.ini"

    if not alembic_ini.exists():
        logger.error("Alembic config not found at %s", alembic_ini)
        return

    cfg = Config(str(alembic_ini))
    cfg.set_main_option("script_location", str(root / "migrations"))
    command.upgrade(cfg, "head")
    logger.info("Database migrations applied.")
