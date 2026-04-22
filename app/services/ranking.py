from __future__ import annotations

from datetime import datetime, timezone
import math
import re

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import AppSetting, Article, Cluster, ClusterEvent, Source
from app.services.source_tiers import source_weight

RANKING_WEIGHTS = {
    "impact": 0.28,
    "confidence": 0.18,
    "corroboration": 0.16,
    "velocity": 0.18,
    "freshness": 0.20,
}

LOCAL_RELEVANCE_BOOST_CAP = 0.35

IMPACT_TERMS = {
    "killed",
    "dead",
    "injured",
    "evacuated",
    "earthquake",
    "wildfire",
    "hurricane",
    "flood",
    "state of emergency",
    "power outage",
    "shutdown",
    "sanctions",
    "curfew",
    "federal",
    "governor",
    "president",
    "declared",
}

US_TERMS = {"u.s.", "us", "united states", "washington", "congress", "white house", "america"}


def rank_clusters(db: Session, cluster_ids: list[int] | None = None) -> None:
    stmt = select(Cluster)
    if cluster_ids:
        stmt = stmt.where(Cluster.id.in_(cluster_ids))

    settings = db.scalar(select(AppSetting).limit(1))
    user_region = ((settings.region if settings else "") or "").strip().lower()
    now = datetime.now(timezone.utc)
    clusters = db.scalars(stmt).all()

    for cluster in clusters:
        articles = db.scalars(
            select(Article).where(Article.cluster_id == cluster.id).order_by(desc(Article.published_at)).limit(40)
        ).all()
        if not articles:
            continue

        cluster.corroboration_count = len({(a.source_name or "").strip().lower() for a in articles if a.source_name})
        source_meta = _source_metadata(db, articles)
        cluster.source_confidence_score = _source_confidence_score(articles, source_meta)
        cluster.impact_score = _impact_score(cluster, articles)
        cluster.local_relevance_score = _local_relevance_score(cluster, articles, user_region)
        cluster.velocity_score = _velocity_score(db, cluster.id, now)
        cluster.freshness_score = _freshness_score(cluster, articles, now)
        cluster.staleness_decay = _staleness_decay(cluster, now)

        source_type_diversity = min(1.0, len({(m.get("source_type") or "") for m in source_meta.values() if m.get("source_type")}) / 4.0)
        geo_diversity = min(1.0, len({(m.get("geography") or "") for m in source_meta.values() if m.get("geography")}) / 5.0)
        corroboration_score = min(1.0, cluster.corroboration_count / 8.0)
        importance = (
            RANKING_WEIGHTS["impact"] * cluster.impact_score
            + RANKING_WEIGHTS["confidence"] * cluster.source_confidence_score
            + RANKING_WEIGHTS["corroboration"] * corroboration_score
            + 0.06 * source_type_diversity
            + 0.05 * geo_diversity
            + RANKING_WEIGHTS["velocity"] * cluster.velocity_score
            + RANKING_WEIGHTS["freshness"] * cluster.freshness_score
        )
        cluster.importance_score = importance

        local_boost = min(LOCAL_RELEVANCE_BOOST_CAP, max(0.0, cluster.local_relevance_score))
        cluster.score = importance * (1 + local_boost) * cluster.staleness_decay
        cluster.cluster_state = _cluster_state(cluster)
        cluster.seeking_confirmation = bool(cluster.impact_score >= 0.65 and cluster.corroboration_count < 2)

    db.commit()


def _source_metadata(db: Session, articles: list[Article]) -> dict[str, dict]:
    names = {a.source_name for a in articles if a.source_name}
    if not names:
        return {}
    rows = db.scalars(select(Source).where(Source.name.in_(names))).all()
    return {
        r.name: {
            "source_type": r.source_type,
            "geography": r.geography,
            "tier": r.source_tier,
            "priority_weight": r.priority_weight,
        }
        for r in rows
    }


def _source_confidence_score(articles: list[Article], source_meta: dict[str, dict]) -> float:
    if not articles:
        return 0.0
    weights = []
    for a in articles:
        meta = source_meta.get(a.source_name or "", {})
        weights.append(
            source_weight(
                a.source_name,
                source_type=meta.get("source_type"),
                tier_override=meta.get("tier"),
                priority_weight=meta.get("priority_weight"),
            )
        )
    return min(1.0, sum(weights) / max(1.0, len(weights)))


def _impact_score(cluster: Cluster, articles: list[Article]) -> float:
    text_parts = [cluster.title or ""]
    for a in articles[:12]:
        text_parts.extend([a.title or "", (a.summary or "")[:280]])
    text = " ".join(text_parts).lower()

    term_hits = sum(1 for term in IMPACT_TERMS if term in text)
    numeric_hits = len(re.findall(r"\b\d{2,}\b", text))
    severity = min(1.0, (term_hits * 0.12) + (numeric_hits * 0.04))
    return max(0.0, severity)


def _local_relevance_score(cluster: Cluster, articles: list[Article], user_region: str) -> float:
    if not user_region:
        return 0.0
    region_tokens = {t.strip().lower() for t in re.split(r"[,\s]+", user_region) if t.strip()}
    if not region_tokens:
        return 0.0

    text_parts = [cluster.title or ""] + [a.title or "" for a in articles[:12]]
    text = " ".join(text_parts).lower()

    matches = sum(1 for token in region_tokens if len(token) > 2 and token in text)
    score = min(1.0, matches * 0.35)

    if any(place in text for place in {"phoenix", "arizona", "maricopa"}):
        score = max(score, 0.4)
    return score


def _velocity_score(db: Session, cluster_id: int, now: datetime) -> float:
    recent_events = db.scalars(
        select(ClusterEvent)
        .where(ClusterEvent.cluster_id == cluster_id)
        .order_by(desc(ClusterEvent.created_at))
        .limit(30)
    ).all()
    if not recent_events:
        return 0.0

    cutoff_seconds = 3600
    events_1h = 0
    for event in recent_events:
        if not event.created_at:
            continue
        age = (now - event.created_at).total_seconds()
        if age <= cutoff_seconds:
            events_1h += 1
    return min(1.0, events_1h / 8.0)


def _freshness_score(cluster: Cluster, articles: list[Article], now: datetime) -> float:
    latest = max([a.published_at for a in articles if a.published_at] + [cluster.updated_at or now])
    age_hours = max(0.0, (now - latest).total_seconds() / 3600)
    return math.exp(-age_hours / 10)


def _staleness_decay(cluster: Cluster, now: datetime) -> float:
    ref = cluster.updated_at or now
    age_hours = max(0.0, (now - ref).total_seconds() / 3600)
    if age_hours <= 12:
        return 1.0
    if age_hours >= 120:
        return 0.2
    return max(0.2, 1.0 - ((age_hours - 12) / 150))


def _cluster_state(cluster: Cluster) -> str:
    if cluster.staleness_decay <= 0.25:
        return "archived"
    if cluster.freshness_score < 0.2 and cluster.velocity_score < 0.1:
        return "fading"
    if cluster.freshness_score < 0.4 and cluster.velocity_score < 0.2:
        return "stabilizing"
    if cluster.importance_score >= 0.72 and cluster.corroboration_count >= 5:
        return "major"
    if cluster.velocity_score >= 0.3 and cluster.freshness_score >= 0.45:
        return "developing"
    return "emerging"


def looks_us_focused(cluster: Cluster) -> bool:
    text = f"{cluster.title or ''} {' '.join(cluster.key_entities or [])}".lower()
    return any(token in text for token in US_TERMS)
