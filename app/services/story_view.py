from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from app.models import Article, Cluster, ClusterEvent
from app.services.summarizer import FALLBACK_SUMMARY, FALLBACK_WHY


@dataclass
class StoryReadiness:
    state: str
    reason: str


def infer_story_status(cluster: Cluster, latest_article_at: datetime | None, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    reference = latest_article_at or cluster.updated_at or cluster.created_at or now
    age_hours = max(0.0, (now - reference).total_seconds() / 3600)

    if (cluster.cluster_state or "") == "archived" or age_hours >= 96:
        return "concluded"
    if age_hours >= 36:
        return "stabilizing"
    if age_hours >= 8:
        return "active"
    return "developing"


def infer_readiness(cluster: Cluster, article_count: int, latest_enrichment: ClusterEvent | None) -> StoryReadiness:
    details = latest_enrichment.details if latest_enrichment and isinstance(latest_enrichment.details, dict) else {}
    stage = (details.get("stage") or "").lower()

    if article_count == 0:
        return StoryReadiness("awaiting_clustering", "Awaiting clustering: no linked articles are attached to this story yet.")
    if stage in {"queued", "processing"}:
        return StoryReadiness("processing", "Processing: background enrichment is currently running.")
    if stage == "failed":
        return StoryReadiness("ai_failed", "AI generation failed: deterministic fallbacks are shown below.")
    if not cluster.ai_summary and not cluster.why_it_matters:
        return StoryReadiness("awaiting_summary", "Awaiting summary: article evidence exists, but synthesis is not ready yet.")
    if not cluster.ai_summary or not cluster.why_it_matters or not (cluster.what_changed or []):
        return StoryReadiness("partial", "Partial data available: some sections are still filling in.")
    return StoryReadiness("ready", "Ready: summary, updates, and evidence are available.")


def latest_change_line(cluster: Cluster, articles: list[Article]) -> tuple[str, bool]:
    changes = [line for line in (cluster.what_changed or []) if line and line.strip()]
    if changes:
        return changes[0], False

    if len(articles) >= 2:
        newest, previous = articles[0], articles[1]
        newest_title = (newest.title or "a newer report").strip()
        previous_title = (previous.title or "an earlier report").strip()
        return f"Latest reporting shifted from '{previous_title}' to '{newest_title}'.", True

    if articles:
        title = (articles[0].title or "a new report").strip()
        return f"A new report was attached: '{title}'.", True

    return "No recent updates yet.", True


def one_line_current_state(cluster: Cluster, articles: list[Article]) -> tuple[str, bool]:
    if cluster.ai_summary and cluster.ai_summary.strip() and cluster.ai_summary.strip() != FALLBACK_SUMMARY:
        sentence = cluster.ai_summary.strip().split(".")[0].strip()
        if sentence:
            return f"{sentence}.", False

    if articles:
        title = (articles[0].title or "Latest coverage is attached").strip()
        return f"Current reporting centers on: {title}.", True

    return "Current state is still being established from incoming coverage.", True


def why_it_matters_line(cluster: Cluster, fallback_line: str) -> tuple[str, bool]:
    text = (cluster.why_it_matters or "").strip()
    if text and text != FALLBACK_WHY:
        return text, False
    return fallback_line, True


def story_status_badge(status: str) -> str:
    labels = {
        "developing": "Developing",
        "active": "Active",
        "stabilizing": "Stabilizing",
        "concluded": "Concluded",
    }
    return labels.get(status, "Developing")
