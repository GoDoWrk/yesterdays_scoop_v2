from datetime import datetime, timezone

from app.models import Article
from app.services.summarizer import _build_structured_deltas


def test_structured_deltas_include_real_changes():
    previous = {
        "entities": ["Old Agency"],
        "source_count": 1,
        "official_count": 0,
    }
    articles = [
        Article(
            title="Governor of Texas announced evacuation of 1200 residents",
            summary="State department confirmed flood levels rose by 15% in Austin.",
            canonical_url="https://example.com/1",
            source_name="Example News",
            published_at=datetime.now(timezone.utc),
        ),
        Article(
            title="FEMA said response teams are deployed",
            summary="Officials said additional shelters opened overnight.",
            canonical_url="https://example.com/2",
            source_name="Wire Two",
            published_at=datetime.now(timezone.utc),
        ),
    ]

    deltas = _build_structured_deltas(
        previous,
        articles,
        {1: [{"source": "Example News", "published_at": "2026-04-22T00:00:00+00:00"}]},
        1,
    )

    joined = " ".join(deltas).lower()
    assert "newly attached report" in joined
    assert "new named actors/entities" in joined
    assert "numbers/metrics" in joined
    assert "official statement" in joined
