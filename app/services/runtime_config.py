from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import engine
from app.models import AppSetting


def get_runtime_overrides() -> dict:
    try:
        with Session(engine) as db:
            settings = db.scalar(select(AppSetting).limit(1))
            if not settings:
                return {}
            return {
                "miniflux_base_url": settings.miniflux_base_url,
                "miniflux_admin_username": settings.miniflux_admin_username,
                "miniflux_admin_password": settings.miniflux_admin_password,
                "meili_url": settings.meili_url,
                "meili_master_key": settings.meili_master_key,
                "ollama_base_url": settings.ollama_base_url,
                "ollama_chat_model": settings.ollama_chat_model,
                "ollama_embed_model": settings.ollama_embed_model,
                "openai_api_key": settings.openai_api_key,
                "openai_model": settings.openai_model,
                "openai_fallback_enabled": settings.openai_fallback_enabled,
                "llm_provider": settings.llm_provider,
            }
    except Exception:
        return {}
