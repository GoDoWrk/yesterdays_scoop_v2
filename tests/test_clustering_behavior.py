from datetime import datetime, timezone
from types import SimpleNamespace

import app.services.clustering as clustering


class DummyDB:
    def __init__(self, unclustered, clusters):
        self._unclustered = unclustered
        self._clusters = clusters
        self.events = []

    def scalars(self, _stmt):
        class _Wrapper:
            def __init__(self, vals):
                self._vals = vals

            def all(self):
                return self._vals

        if self._unclustered is not None:
            vals = self._unclustered
            self._unclustered = None
            return _Wrapper(vals)
        return _Wrapper(self._clusters)

    def add(self, obj):
        self.events.append(obj)

    def flush(self):
        return None

    def execute(self, _stmt):
        return []

    def commit(self):
        return None


def test_clustering_avoids_duplicate_source_url(monkeypatch):
    now = datetime.now(timezone.utc)
    article = SimpleNamespace(
        id=11,
        cluster_id=None,
        embedding=[1.0, 0.0],
        normalized_tokens=["market", "update"],
        title="Market Update",
        summary="",
        published_at=now,
        canonical_url="https://example.com/story",
        source_name="Example",
    )
    cluster = SimpleNamespace(
        id=7,
        title="Market Update",
        updated_at=now,
        semantic_centroid=[1.0, 0.0],
        source_urls=["https://example.com/story"],
        source_count=1,
        update_frequency=1,
        representative_url="https://example.com/story",
    )

    created = {"id": 100}

    def _cluster_factory(**kwargs):
        created["id"] += 1
        return SimpleNamespace(id=created["id"], **kwargs)

    monkeypatch.setattr(clustering, "Cluster", _cluster_factory)
    monkeypatch.setattr(clustering, "ClusterEvent", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(clustering, "LLMService", lambda: SimpleNamespace(embed=lambda _x: [1.0, 0.0]))
    monkeypatch.setattr(clustering, "_refresh_cluster_sources", lambda _db: None)

    db = DummyDB([article], [cluster])
    result = clustering.assign_articles_to_clusters(db)

    assert result["attached"] == 1
    assert article.cluster_id != cluster.id
