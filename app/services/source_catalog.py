from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source

# Curated, layered source strategy: wire + major + analysis + domain + regional + discovery.
DEFAULT_SOURCE_CATALOG: list[dict] = [
    # Primary reporting / wire
    {"name": "Reuters World", "feed_url": "https://feeds.reuters.com/Reuters/worldNews", "tier": 1, "weight": 1.2, "source_type": "wire", "topic": "world", "geography": "global"},
    {"name": "Reuters Business", "feed_url": "https://feeds.reuters.com/reuters/businessNews", "tier": 1, "weight": 1.2, "source_type": "wire", "topic": "business", "geography": "global"},
    {"name": "Reuters Technology", "feed_url": "https://feeds.reuters.com/reuters/technologyNews", "tier": 1, "weight": 1.2, "source_type": "wire", "topic": "tech", "geography": "global"},
    {"name": "AP Top News", "feed_url": "https://feeds.apnews.com/apf-topnews", "tier": 1, "weight": 1.15, "source_type": "wire", "topic": "world", "geography": "us"},
    {"name": "AP Politics", "feed_url": "https://feeds.apnews.com/apf-politics", "tier": 1, "weight": 1.15, "source_type": "wire", "topic": "politics", "geography": "us"},
    # Major outlets
    {"name": "BBC World", "feed_url": "http://feeds.bbci.co.uk/news/world/rss.xml", "tier": 2, "weight": 1.0, "source_type": "major_outlet", "topic": "world", "geography": "uk"},
    {"name": "NPR News", "feed_url": "https://feeds.npr.org/1001/rss.xml", "tier": 2, "weight": 0.95, "source_type": "major_outlet", "topic": "us", "geography": "us"},
    {"name": "NPR Politics", "feed_url": "https://feeds.npr.org/1014/rss.xml", "tier": 2, "weight": 0.95, "source_type": "major_outlet", "topic": "politics", "geography": "us"},
    {"name": "NYTimes Home", "feed_url": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml", "tier": 2, "weight": 0.95, "source_type": "major_outlet", "topic": "us", "geography": "us"},
    {"name": "Washington Post Politics", "feed_url": "http://feeds.washingtonpost.com/rss/politics", "tier": 2, "weight": 0.95, "source_type": "major_outlet", "topic": "politics", "geography": "us"},
    {"name": "WSJ World", "feed_url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml", "tier": 2, "weight": 0.95, "source_type": "major_outlet", "topic": "world", "geography": "us"},
    {"name": "USA Today Nation", "feed_url": "https://www.usatoday.com/rss/news/", "tier": 3, "weight": 0.85, "source_type": "major_outlet", "topic": "us", "geography": "us"},
    {"name": "CBS News", "feed_url": "https://www.cbsnews.com/latest/rss/main", "tier": 3, "weight": 0.8, "source_type": "major_outlet", "topic": "us", "geography": "us"},
    {"name": "ABC News", "feed_url": "https://abcnews.go.com/abcnews/topstories", "tier": 3, "weight": 0.8, "source_type": "major_outlet", "topic": "us", "geography": "us"},
    # Depth / analysis
    {"name": "Financial Times", "feed_url": "https://www.ft.com/rss/home", "tier": 2, "weight": 0.95, "source_type": "analysis", "topic": "business", "geography": "global"},
    {"name": "The Economist", "feed_url": "https://www.economist.com/the-world-this-week/rss.xml", "tier": 2, "weight": 0.9, "source_type": "analysis", "topic": "geopolitics", "geography": "global"},
    {"name": "Foreign Affairs", "feed_url": "https://www.foreignaffairs.com/rss.xml", "tier": 2, "weight": 0.9, "source_type": "analysis", "topic": "geopolitics", "geography": "global"},
    {"name": "Brookings", "feed_url": "https://www.brookings.edu/feed/", "tier": 3, "weight": 0.78, "source_type": "analysis", "topic": "policy", "geography": "us"},
    {"name": "Council on Foreign Relations", "feed_url": "https://www.cfr.org/rss", "tier": 3, "weight": 0.8, "source_type": "analysis", "topic": "geopolitics", "geography": "us"},
    # Domain-specific
    {"name": "TechCrunch", "feed_url": "https://techcrunch.com/feed/", "tier": 3, "weight": 0.8, "source_type": "niche", "topic": "tech", "geography": "global"},
    {"name": "The Verge", "feed_url": "https://www.theverge.com/rss/index.xml", "tier": 3, "weight": 0.78, "source_type": "niche", "topic": "tech", "geography": "us"},
    {"name": "Ars Technica", "feed_url": "https://feeds.arstechnica.com/arstechnica/index", "tier": 3, "weight": 0.78, "source_type": "niche", "topic": "tech", "geography": "us"},
    {"name": "Defense News", "feed_url": "https://www.defensenews.com/arc/outboundfeeds/rss/", "tier": 3, "weight": 0.8, "source_type": "niche", "topic": "defense", "geography": "us"},
    {"name": "Breaking Defense", "feed_url": "https://breakingdefense.com/feed/", "tier": 3, "weight": 0.78, "source_type": "niche", "topic": "defense", "geography": "us"},
    {"name": "EIA Today in Energy", "feed_url": "https://www.eia.gov/todayinenergy/rss.php", "tier": 2, "weight": 0.9, "source_type": "official", "topic": "energy", "geography": "us"},
    {"name": "S&P Global Mobility", "feed_url": "https://www.spglobal.com/mobility/en/rss-feed.html", "tier": 3, "weight": 0.72, "source_type": "niche", "topic": "transportation", "geography": "global"},
    {"name": "Aviation Week", "feed_url": "https://aviationweek.com/rss.xml", "tier": 3, "weight": 0.72, "source_type": "niche", "topic": "transportation", "geography": "global"},
    # Regional + local (Arizona focus)
    {"name": "Arizona Republic", "feed_url": "https://www.azcentral.com/rss/news/", "tier": 3, "weight": 0.82, "source_type": "local", "topic": "arizona", "geography": "arizona"},
    {"name": "Phoenix New Times", "feed_url": "https://www.phoenixnewtimes.com/phoenix/Rss.xml", "tier": 3, "weight": 0.68, "source_type": "local", "topic": "arizona", "geography": "phoenix"},
    {"name": "12News Phoenix", "feed_url": "https://www.12news.com/feeds/syndication/rss/news/local", "tier": 3, "weight": 0.76, "source_type": "local", "topic": "arizona", "geography": "phoenix"},
    {"name": "Texas Tribune", "feed_url": "https://www.texastribune.org/feeds/articles/", "tier": 3, "weight": 0.75, "source_type": "regional", "topic": "us_regional", "geography": "texas"},
    {"name": "CalMatters", "feed_url": "https://calmatters.org/feed/", "tier": 3, "weight": 0.75, "source_type": "regional", "topic": "us_regional", "geography": "california"},
    # International regional
    {"name": "Al Jazeera", "feed_url": "https://www.aljazeera.com/xml/rss/all.xml", "tier": 2, "weight": 0.9, "source_type": "major_outlet", "topic": "world", "geography": "mena"},
    {"name": "DW Top Stories", "feed_url": "https://rss.dw.com/xml/rss-en-all", "tier": 2, "weight": 0.88, "source_type": "major_outlet", "topic": "world", "geography": "europe"},
    {"name": "France24", "feed_url": "https://www.france24.com/en/rss", "tier": 3, "weight": 0.8, "source_type": "major_outlet", "topic": "world", "geography": "europe"},
    {"name": "The Japan Times", "feed_url": "https://www.japantimes.co.jp/feed/", "tier": 3, "weight": 0.78, "source_type": "regional", "topic": "asia", "geography": "asia"},
    # Aggregator/discovery
    {"name": "Google News World", "feed_url": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en", "tier": 3, "weight": 0.7, "source_type": "aggregator", "topic": "world", "geography": "global"},
    {"name": "Google News U.S.", "feed_url": "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-US&gl=US&ceid=US:en", "tier": 3, "weight": 0.7, "source_type": "aggregator", "topic": "us", "geography": "us"},
    {"name": "Google News Business", "feed_url": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en", "tier": 3, "weight": 0.7, "source_type": "aggregator", "topic": "business", "geography": "global"},
    {"name": "Google News Technology", "feed_url": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en", "tier": 3, "weight": 0.7, "source_type": "aggregator", "topic": "tech", "geography": "global"},
    {"name": "Google News Politics", "feed_url": "https://news.google.com/rss/headlines/section/topic/POLITICS?hl=en-US&gl=US&ceid=US:en", "tier": 3, "weight": 0.7, "source_type": "aggregator", "topic": "politics", "geography": "us"},
]


def default_poll_frequency_for_source(*, source_type: str, tier: int) -> int:
    kind = (source_type or "").strip().lower()
    if kind in {"wire", "aggregator"}:
        return 8
    if kind in {"major_outlet", "official"}:
        return 18
    if kind in {"analysis", "niche", "regional", "local"}:
        return 35
    if tier <= 1:
        return 10
    if tier == 2:
        return 20
    return 45


def default_poll_frequency_for_tier(tier: int) -> int:
    # Backward-compatible helper for callers that only know tier.
    return default_poll_frequency_for_source(source_type="", tier=tier)


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
        "google news": "google_news",
    }
    for key, family in mapping.items():
        if key in lowered:
            return family
    return lowered.split()[0]


def infer_source_metadata(name: str, feed_url: str) -> dict[str, str | int | float]:
    lowered = (name or "").lower()
    host = (urlparse(feed_url).netloc or "").lower()

    source_type = "major_outlet"
    topic = "general"
    geography = "global"
    tier = 3
    weight = 0.75

    if any(k in lowered for k in {"reuters", "associated press", "ap "}):
        source_type, tier, weight = "wire", 1, 1.2
    elif "google.com" in host or "news.google" in host:
        source_type, tier, weight = "aggregator", 3, 0.7
    elif any(k in lowered for k in {"brookings", "foreign affairs", "economist", "cfr"}):
        source_type, tier, weight = "analysis", 2, 0.9
    elif any(k in lowered for k in {"arizona", "phoenix", "azcentral"}):
        source_type, topic, geography, tier, weight = "local", "arizona", "arizona", 3, 0.8

    if any(k in lowered for k in {"business", "markets", "finance"}):
        topic = "business"
    elif any(k in lowered for k in {"tech", "technology"}):
        topic = "tech"
    elif any(k in lowered for k in {"politic", "election", "congress"}):
        topic = "politics"
    elif any(k in lowered for k in {"defense", "military"}):
        topic = "defense"

    return {
        "source_type": source_type,
        "topic": topic,
        "geography": geography,
        "tier": tier,
        "weight": weight,
    }


def seed_source_registry(db: Session) -> int:
    created = 0
    now = datetime.now(timezone.utc)
    for item in DEFAULT_SOURCE_CATALOG:
        existing = db.scalar(select(Source).where(Source.feed_url == item["feed_url"]))
        meta = infer_source_metadata(item["name"], item["feed_url"])
        if existing:
            if not existing.outlet_family:
                existing.outlet_family = source_family(existing.name)
            existing.source_tier = int(item.get("tier") or meta["tier"])
            existing.priority_weight = float(item.get("weight") or meta["weight"])
            existing.weight = existing.priority_weight
            existing.source_type = str(item.get("source_type") or meta["source_type"])
            existing.topic = str(item.get("topic") or meta["topic"])
            existing.geography = str(item.get("geography") or meta["geography"])
            existing.poll_frequency_minutes = int(item.get("poll_frequency_minutes") or default_poll_frequency_for_source(source_type=existing.source_type, tier=existing.source_tier))
            continue
        source = Source(
            name=item["name"],
            feed_url=item["feed_url"],
            source_tier=int(item.get("tier") or meta["tier"]),
            priority_weight=float(item.get("weight") or meta["weight"]),
            poll_frequency_minutes=int(item.get("poll_frequency_minutes") or default_poll_frequency_for_source(source_type=str(item.get("source_type") or meta["source_type"]), tier=int(item.get("tier") or meta["tier"]))),
            enabled=True,
            health_status="unknown",
            failure_count=0,
            average_latency_ms=0.0,
            last_attempted_fetch=None,
            last_successful_fetch=None,
            last_article_time=None,
            outlet_family=source_family(item["name"]),
            weight=float(item.get("weight") or meta["weight"]),
            source_type=str(item.get("source_type") or meta["source_type"]),
            topic=str(item.get("topic") or meta["topic"]),
            geography=str(item.get("geography") or meta["geography"]),
            region=str(item.get("geography") or meta["geography"]),
            created_at=now,
        )
        db.add(source)
        created += 1
    db.commit()
    return created
