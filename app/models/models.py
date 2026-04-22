from datetime import datetime
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Source(Base):
    """Deprecated in favor of Miniflux categories/feeds; retained for backwards compatibility."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    feed_url: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    homepage_url: Mapped[str | None] = mapped_column(String(1024))
    miniflux_feed_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    source_tier: Mapped[int] = mapped_column(Integer, default=3)
    priority_weight: Mapped[float] = mapped_column(Float, default=1.0)
    poll_frequency_minutes: Mapped[int] = mapped_column(Integer, default=30)
    health_status: Mapped[str] = mapped_column(String(32), default="unknown")
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    average_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    last_successful_fetch: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_attempted_fetch: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_article_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outlet_family: Mapped[str | None] = mapped_column(String(128))
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    region: Mapped[str] = mapped_column(String(128), default="global")
    source_type: Mapped[str] = mapped_column(String(32), default="major_outlet")
    topic: Mapped[str] = mapped_column(String(64), default="general")
    geography: Mapped[str] = mapped_column(String(64), default="global")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class FeedFetchState(Base):
    """Deprecated in favor of Miniflux ingestion state."""

    __tablename__ = "feed_fetch_states"

    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
    etag: Mapped[str | None] = mapped_column(String(255))
    last_modified: Mapped[str | None] = mapped_column(String(255))
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class Article(Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("canonical_url", name="uq_articles_canonical_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"), index=True)
    miniflux_entry_id: Mapped[int | None] = mapped_column(Integer, unique=True, index=True)
    miniflux_feed_id: Mapped[int | None] = mapped_column(Integer, index=True)
    source_name: Mapped[str | None] = mapped_column(String(255))
    title: Mapped[str] = mapped_column(String(800), nullable=False)
    canonical_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    original_url: Mapped[str | None] = mapped_column(String(1024))
    author: Mapped[str | None] = mapped_column(String(255))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    summary: Mapped[str | None] = mapped_column(Text)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    extraction_method: Mapped[str | None] = mapped_column(String(64))
    normalized_tokens: Mapped[list[str]] = mapped_column(ARRAY(Text), default=[])
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("clusters.id", ondelete="SET NULL"), index=True)

    source: Mapped["Source"] = relationship()


class Cluster(Base):
    __tablename__ = "clusters"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    representative_article_id: Mapped[int | None] = mapped_column(ForeignKey("articles.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(800), nullable=False)
    ai_summary: Mapped[str | None] = mapped_column(Text)
    why_it_matters: Mapped[str | None] = mapped_column(Text)
    what_changed: Mapped[list[str]] = mapped_column(ARRAY(Text), default=[])
    key_entities: Mapped[list[str]] = mapped_column(ARRAY(Text), default=[])
    representative_url: Mapped[str | None] = mapped_column(String(1024))
    source_urls: Mapped[list[str]] = mapped_column(ARRAY(Text), default=[])
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    update_frequency: Mapped[int] = mapped_column(Integer, default=0)
    impact_score: Mapped[float] = mapped_column(Float, default=0.0)
    local_relevance_score: Mapped[float] = mapped_column(Float, default=0.0)
    source_confidence_score: Mapped[float] = mapped_column(Float, default=0.0)
    corroboration_count: Mapped[int] = mapped_column(Integer, default=0)
    velocity_score: Mapped[float] = mapped_column(Float, default=0.0)
    freshness_score: Mapped[float] = mapped_column(Float, default=0.0)
    staleness_decay: Mapped[float] = mapped_column(Float, default=1.0)
    importance_score: Mapped[float] = mapped_column(Float, default=0.0)
    cluster_state: Mapped[str] = mapped_column(String(32), default="emerging")
    seeking_confirmation: Mapped[bool] = mapped_column(Boolean, default=False)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[float] = mapped_column(Float, default=0.0)
    semantic_centroid: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ClusterEvent(Base):
    __tablename__ = "cluster_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), default="article_attached")
    details: Mapped[dict] = mapped_column(JSONB, default={})
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SocialItem(Base):
    __tablename__ = "social_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("clusters.id", ondelete="CASCADE"), index=True)
    platform: Mapped[str] = mapped_column(String(16), index=True)
    author: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(String(1024), unique=True, nullable=False)
    engagement: Mapped[dict] = mapped_column(JSONB, default={})
    is_verified_source: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())



class AppSetting(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    enable_ai_summarization: Mapped[bool] = mapped_column(Boolean, default=True)
    openai_api_key: Mapped[str | None] = mapped_column(String(255))
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=15)
    region: Mapped[str] = mapped_column(String(64), default="global")
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text), default=[])
    llm_provider: Mapped[str] = mapped_column(String(24), default="ollama")
    miniflux_api_key: Mapped[str | None] = mapped_column(String(255))
    miniflux_base_url: Mapped[str | None] = mapped_column(String(255))
    miniflux_admin_username: Mapped[str | None] = mapped_column(String(128))
    miniflux_admin_password: Mapped[str | None] = mapped_column(String(255))
    miniflux_bootstrap_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    miniflux_bootstrap_error: Mapped[str | None] = mapped_column(Text)
    miniflux_last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    miniflux_retry_count: Mapped[int] = mapped_column(Integer, default=0)
    source_preset: Mapped[str] = mapped_column(String(32), default="balanced")
    homepage_section_limit: Mapped[int] = mapped_column(Integer, default=6)
    homepage_show_fast_moving: Mapped[bool] = mapped_column(Boolean, default=True)
    homepage_show_recently_updated: Mapped[bool] = mapped_column(Boolean, default=True)
    ranking_impact_weight: Mapped[float] = mapped_column(Float, default=0.28)
    ranking_freshness_weight: Mapped[float] = mapped_column(Float, default=0.20)
    confirmation_impact_threshold: Mapped[float] = mapped_column(Float, default=0.65)
    backup_schedule_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    backup_schedule_cron: Mapped[str] = mapped_column(String(64), default="0 3 * * *")
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    local_relevance_preference: Mapped[str] = mapped_column(String(32), default="medium")
    meili_url: Mapped[str | None] = mapped_column(String(255))
    meili_master_key: Mapped[str | None] = mapped_column(String(255))
    ollama_base_url: Mapped[str | None] = mapped_column(String(255))
    ollama_chat_model: Mapped[str | None] = mapped_column(String(128))
    ollama_embed_model: Mapped[str | None] = mapped_column(String(128))
    openai_model: Mapped[str | None] = mapped_column(String(128))
    openai_fallback_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_social_context: Mapped[bool] = mapped_column(Boolean, default=False)
    enable_reddit_context: Mapped[bool] = mapped_column(Boolean, default=True)
    enable_x_context: Mapped[bool] = mapped_column(Boolean, default=False)
    social_max_items: Mapped[int] = mapped_column(Integer, default=8)
    x_api_bearer_token: Mapped[str | None] = mapped_column(String(255))
    setup_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    setup_last_step: Mapped[int] = mapped_column(Integer, default=1)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())




class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(24), default="running")
    ingested_count: Mapped[int] = mapped_column(Integer, default=0)
    clustered_count: Mapped[int] = mapped_column(Integer, default=0)
    summarized_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_clusters_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_articles_count: Mapped[int] = mapped_column(Integer, default=0)
    stage_error_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)


class PipelineStageEvent(Base):
    __tablename__ = "pipeline_stage_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("pipeline_runs.id", ondelete="CASCADE"), index=True)
    stage: Mapped[str] = mapped_column(String(32), index=True)
    status: Mapped[str] = mapped_column(String(24), default="success")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSONB, default={})
    error: Mapped[str | None] = mapped_column(Text)

class ServiceState(Base):
    __tablename__ = "service_state"

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    scheduler_last_tick_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_pipeline_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_pipeline_finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_pipeline_success: Mapped[bool | None] = mapped_column(Boolean)
    last_pipeline_stage: Mapped[str | None] = mapped_column(String(32))
    last_pipeline_error: Mapped[str | None] = mapped_column(Text)
    last_ingest_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_clustering_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_summarization_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_ranking_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
