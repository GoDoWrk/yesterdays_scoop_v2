import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AppSetting, Article, Cluster
from app.services.llm import LLMService

logger = logging.getLogger(__name__)


CONCRETE_FACT_PATTERN = re.compile(r"(\d+|agency:|location:|injured|killed|evacuated|declared)", re.IGNORECASE)


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
        articles = db.scalars(select(Article).where(Article.cluster_id == cluster.id).limit(8)).all()
        if not articles:
            continue

        concrete_changes = _concrete_what_changed(changes_by_cluster or {}, cluster.id)
        should_regenerate = bool(concrete_changes) or not (cluster.ai_summary and cluster.why_it_matters)

        if not should_regenerate:
            continue

        payload = [
            {
                "title": a.title,
                "summary": a.summary,
                "text": (a.extracted_text or "")[:1200],
                "url": a.canonical_url,
                "source": a.source_name,
            }
            for a in articles
        ]

        data = None
        if ai_enabled and concrete_changes:
            try:
                data = llm.summarize_cluster(payload)
            except Exception as exc:
                logger.warning("Summarization provider error for cluster %s: %s", cluster.id, exc)

        if not data:
            logger.info("Using extractive summary fallback for cluster %s", cluster.id)
            data = _extractive_fallback(cluster, articles)

        cluster.title = data.get("cluster_title", cluster.title)
        cluster.ai_summary = data.get("summary")
        cluster.why_it_matters = data.get("why_it_matters")

        generated_changes = [c for c in data.get("what_changed", []) if _is_meaningful_change_line(c)]
        cluster.what_changed = (concrete_changes + generated_changes)[:3]

        cluster.key_entities = data.get("key_entities", [])
        cluster.representative_url = data.get("representative_url", cluster.representative_url)
        cluster.source_urls = data.get("source_urls", cluster.source_urls)
        updated_cluster_ids.append(cluster.id)

    db.commit()
    return updated_cluster_ids


def _concrete_what_changed(changes_by_cluster: dict[int, list[dict[str, str | None]]], cluster_id: int) -> list[str]:
    deltas = changes_by_cluster.get(cluster_id, [])
    if not deltas:
        return []

    source_names = sorted({d.get("source") for d in deltas if d.get("source")})
    latest = max((d.get("published_at") for d in deltas if d.get("published_at")), default=None)
    fact_tokens = [d.get("facts") for d in deltas if d.get("facts")]
    material_facts = [f for f in fact_tokens if CONCRETE_FACT_PATTERN.search(f or "")]

    lines = [f"{len(deltas)} new report(s) added from {len(source_names) or 1} source(s)."]
    if material_facts:
        lines.append(f"New concrete signals: {material_facts[0][:120]}.")
    if latest:
        lines.append(f"Latest newly attached report timestamp: {latest}.")
    return lines[:3]


def _extractive_fallback(cluster: Cluster, articles: list[Article]) -> dict:
    titles = [a.title for a in articles if a.title]
    source_urls = [a.canonical_url for a in articles if a.canonical_url]
    return {
        "cluster_title": cluster.title,
        "summary": " ".join(titles[:3]),
        "why_it_matters": "Coverage is evolving across multiple outlets and may affect follow-on stories.",
        "what_changed": [f"{len(articles)} source updates currently attached to this cluster."],
        "key_entities": list({token.title() for a in articles for token in (a.normalized_tokens or [])[:2]})[:8],
        "representative_url": source_urls[0] if source_urls else cluster.representative_url,
        "source_urls": source_urls or cluster.source_urls,
    }


def _is_meaningful_change_line(value: str) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return False
    low_value_markers = [
        "coverage is evolving",
        "source updates currently attached",
        "may affect follow-on stories",
    ]
    return not any(marker in text for marker in low_value_markers)
