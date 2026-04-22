from types import SimpleNamespace

import app.tasks.pipeline as pipeline


class DummyDB:
    def __init__(self):
        self.state = SimpleNamespace(
            last_pipeline_started_at=None,
            last_pipeline_success=None,
            last_pipeline_error=None,
            last_pipeline_finished_at=None,
            last_pipeline_stage=None,
        )
        self.added = []
        self._next_id = 1

    def commit(self):
        return None

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1
        self.added.append(obj)

    def refresh(self, _obj):
        return None


class DummySessionFactory:
    def __init__(self, db):
        self.db = db

    def __call__(self):
        return self

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, tb):
        return False


def test_pipeline_records_stage_history(monkeypatch):
    db = DummyDB()

    monkeypatch.setattr(pipeline, "SessionLocal", DummySessionFactory(db))
    monkeypatch.setattr(pipeline, "get_or_create_service_state", lambda _db: db.state)
    monkeypatch.setattr(pipeline, "ingest_from_miniflux", lambda _db: {"inserted": 2, "inserted_article_ids": [1], "processed_entry_ids": [10]})
    monkeypatch.setattr(
        pipeline,
        "assign_articles_to_clusters",
        lambda _db: {"attached": 2, "touched_cluster_ids": [2], "new_articles_by_cluster": {2: []}},
    )
    monkeypatch.setattr(pipeline, "summarize_clusters", lambda _db, **kwargs: [2])
    monkeypatch.setattr(pipeline, "rank_clusters", lambda _db, **kwargs: None)
    monkeypatch.setattr(pipeline, "ingest_social_context", lambda _db, **kwargs: {"clusters": 0, "items": 0})
    monkeypatch.setattr(
        pipeline,
        "MeiliService",
        lambda: SimpleNamespace(index_from_db=lambda _db, **kwargs: {"articles": 2, "clusters": 1}),
    )

    pipeline.run_pipeline()

    stage_events = [obj for obj in db.added if obj.__class__.__name__ == "PipelineStageEvent"]
    stage_names = {event.stage for event in stage_events}

    assert {"ingest", "cluster", "summarize", "rank", "social", "index"}.issubset(stage_names)
