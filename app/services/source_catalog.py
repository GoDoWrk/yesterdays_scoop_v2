from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source

DEFAULT_SOURCE_CATALOG: list[dict] = [
    {"name": "Reuters World", "feed_url": "https://feeds.reuters.com/Reuters/worldNews", "tier": 1, "weight": 1.0},
    {"name": "AP News", "feed_url": "https://apnews.com/hub/apf-topnews?output=1", "tier": 1, "weight": 1.0},
    {"name": "BBC World", "feed_url": "http://feeds.bbci.co.uk/news/world/rss.xml", "tier": 2, "weight": 0.9},
    {"name": "NPR News", "feed_url": "https://feeds.npr.org/1001/rss.xml", "tier": 2, "weight": 0.9},
    {"name": "CNN Top", "feed_url": "http://rss.cnn.com/rss/cnn_topstories.rss", "tier": 2, "weight": 0.8},
    {"name": "MSNBC Top", "feed_url": "http://feeds.nbcnews.com/msnbc/public/news", "tier": 2, "weight": 0.7},
    {"name": "WSJ World", "feed_url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml", "tier": 2, "weight": 0.9},
    {"name": "Financial Times", "feed_url": "https://www.ft.com/rss/home", "tier": 2, "weight": 0.85},
    {"name": "LA Times", "feed_url": "https://www.latimes.com/world-nation/rss2.0.xml", "tier": 3, "weight": 0.7},
    {"name": "Chicago Tribune", "feed_url": "https://www.chicagotribune.com/arcio/rss/category/news/", "tier": 3, "weight": 0.65},
]


def default_poll_frequency_for_tier(tier: int) -> int:
    if tier <= 1:
        return 10
    if tier == 2:
        return 20
    return 45


def source_family(name: str | None) -> str | None:
    if not name:
        return None
    lowered = name.lower()
    mapping = {
        "reuters": "reuters",
        "associated press": "ap",
        "ap news": "ap",
        "bbc": "bbc",
        "npr": "npr",
        "cnn": "cnn",
        "msnbc": "nbc",
        "nbc": "nbc",
        "wsj": "wsj",
        "wall street journal": "wsj",
        "financial times": "ft",
        "ft": "ft",
    }
    for key, family in mapping.items():
        if key in lowered:
            return family
    return lowered.split()[0]


def seed_source_registry(db: Session) -> int:
    created = 0
    now = datetime.now(timezone.utc)
    for item in DEFAULT_SOURCE_CATALOG:
        existing = db.scalar(select(Source).where(Source.feed_url == item["feed_url"]))
        if existing:
            if not existing.outlet_family:
                existing.outlet_family = source_family(existing.name)
            continue
        source = Source(
            name=item["name"],
            feed_url=item["feed_url"],
            source_tier=item["tier"],
            priority_weight=item["weight"],
            poll_frequency_minutes=default_poll_frequency_for_tier(item["tier"]),
            enabled=True,
            health_status="unknown",
            failure_count=0,
            average_latency_ms=0.0,
            last_attempted_fetch=None,
            last_successful_fetch=None,
            last_article_time=None,
            outlet_family=source_family(item["name"]),
            weight=item["weight"],
            created_at=now,
        )
        db.add(source)
        created += 1
    db.commit()
    return created
