from datetime import datetime, timedelta, timezone

from app.models import Article, Cluster, ClusterEvent
from app.services.story_view import infer_readiness, infer_story_status, latest_change_line


def _cluster(**overrides):
    base = dict(
        slug="c1",
        title="Demo",
        cluster_state="developing",
        ai_summary="A summary sentence. Another sentence.",
        why_it_matters="It matters.",
        what_changed=["A real change happened."],
        updated_at=datetime.now(timezone.utc),
    )
    base.update(overrides)
    return Cluster(**base)


def test_story_status_transitions_to_concluded_for_old_story():
    cluster = _cluster(cluster_state="stabilizing")
    latest_article_at = datetime.now(timezone.utc) - timedelta(hours=120)

    status = infer_story_status(cluster, latest_article_at)

    assert status == "concluded"


def test_story_status_active_for_mid_age_story():
    cluster = _cluster()
    latest_article_at = datetime.now(timezone.utc) - timedelta(hours=12)

    status = infer_story_status(cluster, latest_article_at)

    assert status == "active"


def test_readiness_marks_ai_failure():
    cluster = _cluster(ai_summary=None, why_it_matters=None, what_changed=[])
    event = ClusterEvent(event_type="enrichment_status", details={"stage": "failed", "reason": "provider_error"})

    readiness = infer_readiness(cluster, article_count=2, latest_enrichment=event)

    assert readiness.state == "ai_failed"


def test_latest_change_falls_back_to_article_delta_when_missing():
    cluster = _cluster(what_changed=[])
    articles = [
        Article(title="Newest title", canonical_url="https://e/new"),
        Article(title="Older title", canonical_url="https://e/old"),
    ]

    line, fallback_used = latest_change_line(cluster, articles)

    assert "Older title" in line
    assert "Newest title" in line
    assert fallback_used is True
