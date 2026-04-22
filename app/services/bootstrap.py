from datetime import datetime, timezone
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppSetting, User
from app.services.auth import hash_password
from app.services.miniflux_client import MinifluxClient
from app.services.source_catalog import DEFAULT_SOURCE_CATALOG, seed_source_registry

DEFAULT_FEEDS = [{"name": s["name"], "feed_url": s["feed_url"]} for s in DEFAULT_SOURCE_CATALOG]
MINIMAL_FEEDS = DEFAULT_FEEDS[:2]
logger = logging.getLogger(__name__)


def bootstrap_data(db: Session) -> None:
    app_settings = ensure_app_settings(db)

    if not app_settings.setup_completed:
        logger.info("Setup wizard incomplete; skipping automatic admin/bootstrap actions.")
        return

    _ensure_default_admin(db)
    seed_source_registry(db)
    attempt_miniflux_bootstrap(db, app_settings=app_settings, reason="startup")


def ensure_app_settings(db: Session) -> AppSetting:
    settings = get_settings()
    app_settings = db.scalar(select(AppSetting).limit(1))
    if app_settings:
        return app_settings

    app_settings = AppSetting(
        enable_ai_summarization=True,
        poll_interval_minutes=15,
        region="global",
        topics=["world", "technology"],
        llm_provider=settings.llm_provider,
        miniflux_base_url=settings.miniflux_base_url,
        miniflux_admin_username=settings.miniflux_admin_username,
        miniflux_admin_password=settings.miniflux_admin_password,
        meili_url=settings.meili_url,
        meili_master_key=settings.meili_master_key,
        ollama_base_url=settings.ollama_base_url,
        ollama_chat_model=settings.ollama_chat_model,
        ollama_embed_model=settings.ollama_embed_model,
        openai_model=settings.openai_model,
        openai_fallback_enabled=True,
        enable_social_context=False,
        enable_reddit_context=True,
        enable_x_context=False,
        social_max_items=8,
        x_api_bearer_token=None,
        source_preset="balanced",
        local_relevance_preference="medium",
        setup_completed=False,
        setup_last_step=1,
    )
    db.add(app_settings)
    db.commit()
    db.refresh(app_settings)
    return app_settings


def attempt_miniflux_bootstrap(db: Session, *, app_settings: AppSetting | None = None, reason: str = "retry") -> bool:
    if app_settings is None:
        app_settings = ensure_app_settings(db)

    if app_settings.miniflux_bootstrap_completed:
        return True

    app_settings.miniflux_last_attempt_at = datetime.now(timezone.utc)
    app_settings.miniflux_retry_count = (app_settings.miniflux_retry_count or 0) + 1
    db.commit()

    logger.info("Miniflux bootstrap attempt #%s (%s)", app_settings.miniflux_retry_count, reason)

    client = MinifluxClient(api_key=app_settings.miniflux_api_key)
    source_preset = getattr(app_settings, "source_preset", "balanced")
    feeds = MINIMAL_FEEDS if source_preset == "minimal" else DEFAULT_FEEDS
    result = client.bootstrap(feeds)

    if not result["ok"]:
        app_settings.miniflux_bootstrap_completed = False
        app_settings.miniflux_bootstrap_error = result["error"]
        db.commit()
        logger.warning("Miniflux bootstrap failed on attempt #%s: %s", app_settings.miniflux_retry_count, result["error"])
        return False

    app_settings.miniflux_bootstrap_completed = True
    app_settings.miniflux_bootstrap_error = None
    if result.get("token"):
        app_settings.miniflux_api_key = result["token"]

    db.commit()
    logger.info(
        "Miniflux bootstrap succeeded on attempt #%s. created=%s skipped=%s",
        app_settings.miniflux_retry_count,
        result["feed_result"]["created"],
        result["feed_result"]["skipped"],
    )
    return True


def _ensure_default_admin(db: Session) -> None:
    settings = get_settings()
    users_count = db.scalar(select(User.id).limit(1))
    if users_count:
        return
    db.add(
        User(
            username=settings.initial_admin_username,
            hashed_password=hash_password(settings.initial_admin_password),
            is_admin=True,
        )
    )
    db.commit()
