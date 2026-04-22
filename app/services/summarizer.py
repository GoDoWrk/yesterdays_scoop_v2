import logging
import re
from datetime import datetime, timezone

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import AppSetting, Article, Cluster, ClusterEvent, SocialItem
from app.services.llm import LLMService

logger = logging.getLogger(__name__)

CONCRETE_FACT_PATTERN = re.compile(
    r"(\d+|agency:|location:|injured|killed|evacuated|declared|confirmed|update|statement)", re.IGNORECASE
)
ENTITY_PATTERN = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})\b")
NUMBER_PATTERN = re.compile(r"\b\d+[\d,]*(?:\.\d+)?%?\b")
OFFICIAL_MARKERS = (
    "said",
    "announced",
    "statement",
    "according to",
    "confirmed",
    "department",
    "ministry",
    "white house",
    "governor",
    "agency",
    "police",
)


FALLBACK_SUMMARY = "We have linked reporting on this story, but AI synthesis is temporarily unavailable."
FALLBACK_WHY = "This cluster is still useful because it tracks corroborated updates and source diversity in one place."


def summarize_clusters(
    db: Session,
    cluster_ids: list[int] | None = None,
    changes_by_cluster: dict[int, list[dict[str, str | None]]] | None = None,
) -> list[int]:
    app_settings = db.scalar(select(AppSetting).limit(1))
    ai_enabled = app_settings.enable_ai_summarization if app_settings else True

    llm = LLMService()
    stmt = select(Cluster)
    if cluster_ids:
        stmt = stmt.where(Cluster.id.in_(cluster_ids))
    clusters = db.scalars(stmt).all()

    updated_cluster_ids: list[int] = []

    for cluster in clusters:
        _record_enrichment_event(db, cluster.id, "queued", reason=None)
        articles = db.scalars(
            select(Article).where(Article.cluster_id == cluster.id).order_by(desc(Article.published_at)).limit(12)
        ).all()
        if not articles:
            _record_enrichment_event(db, cluster.id, "skipped", reason="cluster has no attached articles")
            continue

        previous = {
            "summary": cluster.ai_summary,
            "why": cluster.why_it_matters,
            "what_changed": list(cluster.what_changed or []),
            "entities": list(cluster.key_entities or []),
            "source_count": cluster.source_count or 0,
            "latest_time": cluster.updated_at,
            "official_count": _count_official_social(db, cluster.id),
        }

        concrete_changes = _build_structured_deltas(previous, articles, changes_by_cluster or {}, cluster.id)
        should_regenerate = bool(concrete_changes) or not (cluster.ai_summary and cluster.why_it_matters)

        if not should_regenerate:
            _record_enrichment_event(db, cluster.id, "skipped", reason="no meaningful delta and enrichment already present")
            continue

        _record_enrichment_event(db, cluster.id, "processing", reason=None)

        payload = [
            {
                "title": a.title,
                "summary": a.summary,
                "text": (a.extracted_text or "")[:1200],
                "url": a.canonical_url,
                "source": a.source_name,
                "published_at": a.published_at.isoformat() if a.published_at else None,
            }
            for a in articles
        ]

        data = None
        failure_reason = None
        if ai_enabled:
            try:
                data = llm.summarize_cluster(payload)
            except Exception as exc:
                failure_reason = f"provider_error:{exc}"
                logger.warning("Summarization provider error for cluster %s: %s", cluster.id, exc)
        else:
            failure_reason = "ai_disabled"

        if not data:
            logger.info("Using extractive summary fallback for cluster %s", cluster.id)
            data = _extractive_fallback(cluster, articles, concrete_changes)

        cluster.title = _safe_text(data.get("cluster_title")) or cluster.title
        cluster.ai_summary = _safe_sentences(data.get("summary"), min_sentences=2, max_sentences=3) or FALLBACK_SUMMARY
        cluster.why_it_matters = _safe_sentences(data.get("why_it_matters"), min_sentences=1, max_sentences=2) or FALLBACK_WHY

        generated_changes = [c for c in data.get("what_changed", []) if _is_meaningful_change_line(c)]
        merged_changes = _dedupe_preserve_order(concrete_changes + generated_changes)
        cluster.what_changed = merged_changes[:5] or ["No material delta detected in newly attached coverage."]

        entities = [_safe_text(v) for v in (data.get("key_entities") or [])]
        entities = [e for e in entities if e]
        cluster.key_entities = entities[:10] or _extract_entities_from_articles(articles)[:10]
        cluster.representative_url = _safe_text(data.get("representative_url")) or cluster.representative_url
        source_urls = [u for u in (data.get("source_urls") or []) if isinstance(u, str) and u.strip()]
        cluster.source_urls = _dedupe_preserve_order(source_urls)[:20] or cluster.source_urls

        evidence = _evidence_metadata(cluster, articles)
        status = "success" if not failure_reason else "failed"
        _record_enrichment_event(
            db,
            cluster.id,
            status,
            reason=failure_reason,
            evidence=evidence,
            fallback_used=bool(failure_reason),
            what_changed_count=len(cluster.what_changed or []),
        )

        updated_cluster_ids.append(cluster.id)

    db.commit()
    return updated_cluster_ids


def _build_structured_deltas(
    previous: dict,
    articles: list[Article],
    changes_by_cluster: dict[int, list[dict[str, str | None]]],
    cluster_id: int,
) -> list[str]:
    lines: list[str] = []
    deltas = changes_by_cluster.get(cluster_id, [])

    if deltas:
        source_names = sorted({d.get("source") for d in deltas if d.get("source")})
        lines.append(f"{len(deltas)} newly attached report(s) from {len(source_names) or 1} source(s).")

    recent_articles = articles[:8]
    text_blob = " ".join(f"{a.title or ''} {(a.summary or '')[:240]}" for a in recent_articles)
    entities_now = set(_extract_entities(text_blob)[:20])
    entities_before = {e for e in previous.get("entities", []) if e}
    new_entities = sorted(entities_now - entities_before)
    if new_entities:
        lines.append(f"New named actors/entities: {', '.join(new_entities[:4])}.")

    numbers_now = set(NUMBER_PATTERN.findall(text_blob))
    if numbers_now:
        lines.append(f"Newly reported numbers/metrics mention: {', '.join(sorted(numbers_now)[:4])}.")

    latest_added = max((d.get("published_at") for d in deltas if d.get("published_at")), default=None)
    if latest_added:
        lines.append(f"Latest added report timestamp: {latest_added}.")

    official_statement = _find_official_statement(recent_articles)
    if official_statement:
        lines.append(f"New official statement signal: {official_statement}.")

    current_official_count = sum(1 for a in recent_articles if _looks_official_article(a))
    if current_official_count > (previous.get("official_count") or 0):
        lines.append("Official-response coverage increased in this cycle.")

    if (previous.get("source_count") or 0) and (len({a.source_name for a in articles if a.source_name}) > previous.get("source_count", 0)):
        lines.append("Source diversity increased versus prior cluster state.")

    return [line for line in _dedupe_preserve_order(lines) if _is_meaningful_change_line(line)][:5]


def _extractive_fallback(cluster: Cluster, articles: list[Article], concrete_changes: list[str]) -> dict:
    titles = [a.title for a in articles if a.title]
    source_urls = [a.canonical_url for a in articles if a.canonical_url]
    top_titles = "; ".join(titles[:3])
    return {
        "cluster_title": cluster.title,
        "summary": f"{top_titles}." if top_titles else FALLBACK_SUMMARY,
        "why_it_matters": FALLBACK_WHY,
        "what_changed": concrete_changes or ["No material delta detected in newly attached coverage."],
        "key_entities": _extract_entities_from_articles(articles)[:8],
        "representative_url": source_urls[0] if source_urls else cluster.representative_url,
        "source_urls": source_urls or cluster.source_urls,
    }


def _count_official_social(db: Session, cluster_id: int) -> int:
    items = db.scalars(select(SocialItem).where(SocialItem.cluster_id == cluster_id).limit(100)).all()
    return len([i for i in items if i.is_verified_source])


def _record_enrichment_event(
    db: Session,
    cluster_id: int,
    stage: str,
    reason: str | None,
    evidence: dict | None = None,
    fallback_used: bool | None = None,
    what_changed_count: int | None = None,
) -> None:
    details = {"stage": stage, "reason": reason, "recorded_at": datetime.now(timezone.utc).isoformat()}
    if evidence is not None:
        details["evidence"] = evidence
    if fallback_used is not None:
        details["fallback_used"] = fallback_used
    if what_changed_count is not None:
        details["what_changed_count"] = what_changed_count
    db.add(ClusterEvent(cluster_id=cluster_id, event_type="enrichment_status", details=details))


def _evidence_metadata(cluster: Cluster, articles: list[Article]) -> dict:
    source_names = {(a.source_name or "").strip().lower() for a in articles if a.source_name}
    latest = max((a.published_at for a in articles if a.published_at), default=None)
    freshness_minutes = None
    if latest:
        freshness_minutes = int(max(0.0, (datetime.now(timezone.utc) - latest).total_seconds() // 60))
    return {
        "supporting_sources": cluster.source_count or len(articles),
        "source_diversity": len(source_names),
        "freshness_minutes": freshness_minutes,
    }


def _safe_text(value) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()


def _safe_sentences(value, *, min_sentences: int, max_sentences: int) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", text) if p.strip()]
    if len(parts) < min_sentences:
        return ""
    return " ".join(parts[:max_sentences])


def _extract_entities(text: str) -> list[str]:
    candidates = [m.group(1).strip() for m in ENTITY_PATTERN.finditer(text or "")]
    cleaned = []
    for c in candidates:
        if len(c) < 3:
            continue
        if c.lower() in {"the", "a", "an", "this", "that"}:
            continue
        cleaned.append(c)
    return _dedupe_preserve_order(cleaned)


def _extract_entities_from_articles(articles: list[Article]) -> list[str]:
    blob = " ".join(f"{a.title or ''} {(a.summary or '')[:180]}" for a in articles[:10])
    return _extract_entities(blob)


def _find_official_statement(articles: list[Article]) -> str | None:
    for article in articles:
        text = f"{article.title or ''} {(article.summary or '')[:280]}".lower()
        if any(marker in text for marker in OFFICIAL_MARKERS):
            return (article.title or "Official statement referenced")[:120]
    return None


def _looks_official_article(article: Article) -> bool:
    text = f"{article.title or ''} {(article.summary or '')[:220]}".lower()
    return any(marker in text for marker in OFFICIAL_MARKERS)


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        normalized = (item or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(item.strip())
    return out


def _is_meaningful_change_line(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    low_value_markers = [
        "coverage is evolving",
        "source updates currently attached",
        "may affect follow-on stories",
        "story is still unfolding",
    ]
    return not any(marker in text for marker in low_value_markers)
