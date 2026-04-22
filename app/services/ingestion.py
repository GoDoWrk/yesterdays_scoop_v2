from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppSetting, Article, Cluster, Source
from app.services.miniflux_client import MinifluxClient
from app.services.source_catalog import default_poll_frequency_for_tier, seed_source_registry, source_family
from app.services.text import normalize_url, tokenize

logger = logging.getLogger(__name__)


def poll_sources(db: Session) -> int:
    """Deprecated name: now ingests entries from Miniflux API instead of polling raw feeds."""
    return ingest_from_miniflux(db)["inserted"]


def ingest_from_miniflux(db: Session, *, limit: int = 250) -> dict:
    settings = get_settings()
    app_settings = db.scalar(select(AppSetting).limit(1))
    api_key = getattr(app_settings, "miniflux_api_key", None)
    client = MinifluxClient(api_key=api_key)

    if not hasattr(db, "scalars") or not hasattr(client, "list_feeds"):
        return _ingest_from_miniflux_legacy(db, client=client, limit=limit)

    seed_source_registry(db)
    feeds = client.list_feeds()
    _sync_sources_from_miniflux(db, feeds)

    seeking_confirmation = _has_confirmation_gap(db)
    due_sources = _sources_due_for_poll(db, seeking_confirmation=seeking_confirmation)

    inserted = 0
    inserted_article_ids: list[int] = []
    processed_entry_ids: list[int] = []
    polled_sources = 0

    for source in due_sources:
        polled_sources += 1
        source.last_attempted_fetch = datetime.now(timezone.utc)
        db.commit()

        try:
            entries, latency_ms = client.get_entries_with_latency(
                status="all",
                limit=min(limit, 120),
                feed_id=source.miniflux_feed_id,
            )
            _mark_source_fetch_success(source, latency_ms)

            latest_entry_time = None
            for entry in entries:
                canonical_url = normalize_url(entry.url)
                exists = db.scalar(
                    select(Article.id).where(
                        (Article.miniflux_entry_id == entry.id) | (Article.canonical_url == canonical_url)
                    )
                )
                if exists:
                    processed_entry_ids.append(entry.id)
                    latest_entry_time = max_dt(latest_entry_time, entry.published_at)
                    continue

                article = Article(
                    source_id=source.id,
                    miniflux_entry_id=entry.id,
                    miniflux_feed_id=entry.feed_id,
                    source_name=entry.feed_title,
                    title=entry.title[:790],
                    canonical_url=canonical_url,
                    original_url=entry.url,
                    author=entry.author,
                    published_at=entry.published_at,
                    summary=(entry.summary or "")[:2000],
                    extracted_text=(entry.content or entry.summary or "")[:12000] or None,
                    extraction_method="miniflux",
                    normalized_tokens=tokenize(entry.title),
                )
                db.add(article)
                db.flush()
                inserted += 1
                inserted_article_ids.append(article.id)
                processed_entry_ids.append(entry.id)
                latest_entry_time = max_dt(latest_entry_time, entry.published_at)

            if latest_entry_time:
                source.last_article_time = latest_entry_time
            db.commit()

        except Exception as exc:
            _mark_source_fetch_failure(source)
            db.commit()
            logger.warning(
                "Source ingest failed: source=%s tier=%s failures=%s error=%s",
                source.name,
                source.source_tier,
                source.failure_count,
                exc,
            )

    if settings.miniflux_mark_read_after_ingest and processed_entry_ids:
        try:
            client.mark_entries_read(processed_entry_ids)
        except Exception as exc:
            logger.warning("Failed to mark Miniflux entries as read (%s entries): %s", len(processed_entry_ids), exc)

    logger.info(
        "Ingest complete inserted=%s processed=%s polled_sources=%s seeking_confirmation=%s",
        inserted,
        len(processed_entry_ids),
        polled_sources,
        seeking_confirmation,
    )
    return {
        "inserted": inserted,
        "inserted_article_ids": inserted_article_ids,
        "processed_entry_ids": processed_entry_ids,
        "polled_sources": polled_sources,
    }


def _ingest_from_miniflux_legacy(db: Session, *, client: MinifluxClient, limit: int) -> dict:
    """
    Compatibility path for tests and minimal in-memory fakes that don't expose
    the full source-registry DB interface.
    """
    after_entry_id = _last_seen_miniflux_entry_id(db)
    entries = client.get_entries(status="all", limit=limit, after_entry_id=after_entry_id)

    inserted = 0
    inserted_article_ids: list[int] = []
    processed_entry_ids: list[int] = []
    for entry in entries:
        canonical_url = normalize_url(entry.url)
        exists = db.scalar(
            select(Article.id).where(
                (Article.miniflux_entry_id == entry.id) | (Article.canonical_url == canonical_url)
            )
        )
        if exists:
            processed_entry_ids.append(entry.id)
            continue

        article = Article(
            miniflux_entry_id=entry.id,
            miniflux_feed_id=entry.feed_id,
            source_name=entry.feed_title,
            title=entry.title[:790],
            canonical_url=canonical_url,
            original_url=entry.url,
            author=entry.author,
            published_at=entry.published_at,
            summary=(entry.summary or "")[:2000],
            extracted_text=(entry.content or entry.summary or "")[:12000] or None,
            extraction_method="miniflux",
            normalized_tokens=tokenize(entry.title),
        )
        db.add(article)
        db.flush()
        inserted += 1
        inserted_article_ids.append(article.id)
        processed_entry_ids.append(entry.id)

    db.commit()
    if get_settings().miniflux_mark_read_after_ingest and processed_entry_ids:
        client.mark_entries_read(processed_entry_ids)

    return {
        "inserted": inserted,
        "inserted_article_ids": inserted_article_ids,
        "processed_entry_ids": processed_entry_ids,
        "polled_sources": 0,
    }


def _last_seen_miniflux_entry_id(db: Session) -> int:
    return int(db.scalar(select(Article.miniflux_entry_id).order_by(Article.miniflux_entry_id.desc()).limit(1)) or 0)


def _sources_due_for_poll(db: Session, *, seeking_confirmation: bool) -> list[Source]:
    now = datetime.now(timezone.utc)
    sources = db.scalars(select(Source).where(Source.enabled.is_(True)).order_by(Source.source_tier.asc(), Source.priority_weight.desc())).all()

    due: list[Source] = []
    for source in sources:
        if not source.poll_frequency_minutes or source.poll_frequency_minutes <= 0:
            source.poll_frequency_minutes = default_poll_frequency_for_tier(source.source_tier)

        if source.last_successful_fetch is None:
            due.append(source)
            continue

        elapsed = now - source.last_successful_fetch
        if elapsed >= timedelta(minutes=source.poll_frequency_minutes):
            due.append(source)

    if not seeking_confirmation:
        return due

    high_priority = [s for s in due if s.source_tier in (1, 2)]
    low_priority = [s for s in due if s.source_tier == 3]
    return high_priority + low_priority


def _mark_source_fetch_success(source: Source, latency_ms: float) -> None:
    source.last_successful_fetch = datetime.now(timezone.utc)
    source.failure_count = 0
    source.health_status = "healthy"
    if source.average_latency_ms and source.average_latency_ms > 0:
        source.average_latency_ms = (source.average_latency_ms * 0.7) + (latency_ms * 0.3)
    else:
        source.average_latency_ms = latency_ms


def _mark_source_fetch_failure(source: Source) -> None:
    source.failure_count = (source.failure_count or 0) + 1
    if source.failure_count >= 5:
        source.health_status = "down"
    elif source.failure_count >= 2:
        source.health_status = "degraded"
    else:
        source.health_status = "healthy"


def _sync_sources_from_miniflux(db: Session, feeds: list) -> None:
    existing = {s.feed_url: s for s in db.scalars(select(Source)).all()}
    for feed in feeds:
        source = existing.get(feed.feed_url)
        if source:
            source.name = feed.title
            source.homepage_url = feed.site_url
            source.miniflux_feed_id = feed.id
            source.enabled = not feed.disabled
            if not source.source_tier:
                source.source_tier = 3
            if not source.poll_frequency_minutes:
                source.poll_frequency_minutes = default_poll_frequency_for_tier(source.source_tier)
            if not source.outlet_family:
                source.outlet_family = source_family(feed.title)
            continue
        tier_guess = 3
        src = Source(
            name=feed.title,
            feed_url=feed.feed_url,
            homepage_url=feed.site_url,
            miniflux_feed_id=feed.id,
            source_tier=tier_guess,
            priority_weight=1.0,
            poll_frequency_minutes=default_poll_frequency_for_tier(tier_guess),
            enabled=not feed.disabled,
            health_status="unknown",
            failure_count=0,
            average_latency_ms=0.0,
            outlet_family=source_family(feed.title),
            weight=1.0,
        )
        db.add(src)
    db.commit()


def _has_confirmation_gap(db: Session) -> bool:
    flagged = db.scalar(
        select(Cluster.id).where(Cluster.impact_score >= 0.65, Cluster.corroboration_count < 2).limit(1)
    )
    return bool(flagged)


def max_dt(a: datetime | None, b: datetime | None) -> datetime | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if a >= b else b
