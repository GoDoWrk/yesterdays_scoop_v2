from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Yesterday's Scoop"
    environment: str = "dev"
    database_url: str = "postgresql+psycopg://scoop:scoop@app_db:5432/scoop"
    redis_url: str = "redis://redis:6379/0"

    # LLM
    llm_provider: str = "ollama"  # ollama|openai
    ollama_base_url: str = "http://ollama:11434"
    ollama_chat_model: str = "llama3.1:8b"
    ollama_embed_model: str = "nomic-embed-text"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4.1-mini"

    # Miniflux
    miniflux_base_url: str = "http://miniflux:8080"
    miniflux_api_key: str = ""
    miniflux_admin_username: str = "admin"
    miniflux_admin_password: str = "admin123"
    miniflux_app_api_key_name: str = "yesterdays-scoop"
    miniflux_timeout_seconds: int = 20
    miniflux_mark_read_after_ingest: bool = True


    # Social context
    enable_social_context: bool = False
    enable_reddit_context: bool = True
    enable_x_context: bool = False
    social_max_items: int = 8
    x_api_bearer_token: str | None = None
    # Meilisearch
    meili_url: str = "http://meilisearch:7700"
    meili_master_key: str = "masterKey"

    enable_ai_summarization: bool = True
    poll_interval_minutes: int = 15
    default_region: str = "Global"
    default_topics: str = "world,politics,business,technology,science"
    auth_secret: str = "change-me-in-production"
    initial_admin_username: str = "admin"
    initial_admin_password: str = "admin"


@lru_cache
def get_settings() -> Settings:
    return Settings()
