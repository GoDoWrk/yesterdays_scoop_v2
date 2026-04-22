"""Seed deterministic demo data for story cards/detail testing."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete

from app.db.session import SessionLocal
from app.models import Article, Cluster, ClusterEvent, Source


STORIES = [
    {
        "slug": "demo-ready-grid-outage",
        "title": "Grid outage recovery enters final phase",
        "state": "developing",
        "summary": "Regional utilities reported power restoration in most districts after overnight outages.",
        "why": "Power availability affects transportation, hospitals, and local business continuity.",
        "what_changed": ["Utility authority reported restoration reaching 92% of affected customers."],
        "hours_ago": 2,
    },
    {
        "slug": "demo-partial-flooding",
        "title": "Flood response expands as river levels rise",
        "state": "emerging",
        "summary": None,
        "why": "Emergency services are positioning resources across nearby counties.",
        "what_changed": [],
        "hours_ago": 10,
    },
    {
        "slug": "demo-ai-failed-transit",
        "title": "Transit labor talks continue under mediation",
        "state": "developing",
        "summary": "We have linked reporting on this story, but AI synthesis is temporarily unavailable.",
        "why": "This cluster is still useful because it tracks corroborated updates and source diversity in one place.",
        "what_changed": [],
        "hours_ago": 5,
        "failed": True,
    },
    {
        "slug": "demo-concluded-storm",
        "title": "Storm cleanup winds down after final inspections",
        "state": "stabilizing",
        "summary": "City inspectors reported most critical infrastructure repairs are complete.",
        "why": "Residents still need service restoration updates and insurance guidance.",
        "what_changed": ["No new major damage reports in the latest cycle."],
        "hours_ago": 132,
    },
]


def _source(db, name: str, feed_url: str) -> Source:
    src = db.query(Source).filter(Source.feed_url == feed_url).first()
    if src:
        return src
    src = Source(name=name, feed_url=feed_url, source_tier=2, source_type="major_outlet", enabled=True)
    db.add(src)
    db.flush()
    return src


def main() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.execute(delete(ClusterEvent).where(ClusterEvent.cluster_id.in_(db.query(Cluster.id).filter(Cluster.slug.like("demo-%")))))
        db.execute(delete(Article).where(Article.cluster_id.in_(db.query(Cluster.id).filter(Cluster.slug.like("demo-%")))))
        db.execute(delete(Cluster).where(Cluster.slug.like("demo-%")))
        db.commit()

        source_a = _source(db, "Demo Wire", "https://demo.example/feed-a.xml")
        source_b = _source(db, "City Desk", "https://demo.example/feed-b.xml")

        for idx, story in enumerate(STORIES, start=1):
            touched_at = now - timedelta(hours=story["hours_ago"])
            cluster = Cluster(
                slug=story["slug"],
                title=story["title"],
                ai_summary=story["summary"],
                why_it_matters=story["why"],
                what_changed=story["what_changed"],
                cluster_state=story["state"],
                source_count=2,
                corroboration_count=2,
                freshness_score=0.75 if story["hours_ago"] < 24 else 0.25,
                updated_at=touched_at,
                created_at=touched_at - timedelta(hours=4),
            )
            db.add(cluster)
            db.flush()

            article_1 = Article(
                cluster_id=cluster.id,
                source_id=source_a.id,
                source_name=source_a.name,
                title=f"{story['title']} - first report",
                canonical_url=f"https://demo.example/{story['slug']}/1",
                summary="Initial report",
                published_at=touched_at - timedelta(hours=2),
            )
            article_2 = Article(
                cluster_id=cluster.id,
                source_id=source_b.id,
                source_name=source_b.name,
                title=f"{story['title']} - latest update",
                canonical_url=f"https://demo.example/{story['slug']}/2",
                summary="Follow-up update",
                published_at=touched_at,
            )
            db.add_all([article_1, article_2])

            stage = "failed" if story.get("failed") else "success"
            db.add(
                ClusterEvent(
                    cluster_id=cluster.id,
                    event_type="enrichment_status",
                    details={"stage": stage, "reason": "provider_error:demo" if stage == "failed" else None},
                    created_at=touched_at,
                )
            )
            db.add(
                ClusterEvent(
                    cluster_id=cluster.id,
                    event_type="article_attached",
                    details={"note": "demo timeline event", "index": idx},
                    created_at=touched_at - timedelta(hours=1),
                )
            )

        db.commit()
    print("Seeded demo stories: ready, partial, ai-failed, concluded")


if __name__ == "__main__":
    main()
