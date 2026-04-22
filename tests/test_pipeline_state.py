from types import SimpleNamespace

import app.tasks.pipeline as pipeline


class DummyDB:
    def __init__(self):
        self.commits = 0
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
        self.commits += 1

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


def test_pipeline_updates_success_state(monkeypatch):
    db = DummyDB()

    monkeypatch.setattr(pipeline, "SessionLocal", DummySessionFactory(db))
    monkeypatch.setattr(pipeline, "get_or_create_service_state", lambda _db: db.state)
    monkeypatch.setattr(pipeline, "ingest_from_miniflux", lambda _db: {"inserted": 1, "inserted_article_ids": [1], "processed_entry_ids": [10]})
    monkeypatch.setattr(
        pipeline,
        "assign_articles_to_clusters",
        lambda _db: {"attached": 1, "touched_cluster_ids": [2], "new_articles_by_cluster": {2: []}},
    )
    monkeypatch.setattr(pipeline, "summarize_clusters", lambda _db, **kwargs: [2])
    monkeypatch.setattr(pipeline, "rank_clusters", lambda _db, **kwargs: None)
    monkeypatch.setattr(pipeline, "ingest_social_context", lambda _db, **kwargs: {"clusters": 0, "items": 0})
    monkeypatch.setattr(
        pipeline,
        "MeiliService",
        lambda: SimpleNamespace(index_from_db=lambda _db, **kwargs: {"articles": 1, "clusters": 1}),
    )

    result = pipeline.run_pipeline()

    assert result["ingested"] == 1
    assert db.state.last_pipeline_success is True
    assert db.state.last_pipeline_stage == "complete"
    assert result["run_token"]


def test_pipeline_updates_failure_state(monkeypatch):
    db = DummyDB()

    monkeypatch.setattr(pipeline, "SessionLocal", DummySessionFactory(db))
    monkeypatch.setattr(pipeline, "get_or_create_service_state", lambda _db: db.state)
    monkeypatch.setattr(pipeline, "ingest_from_miniflux", lambda _db: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(pipeline, "MeiliService", lambda: SimpleNamespace())

    try:
        pipeline.run_pipeline()
    except RuntimeError:
        pass

    assert db.state.last_pipeline_success is False
    assert "boom" in (db.state.last_pipeline_error or "")
    assert db.state.last_pipeline_stage == "ingest"


def test_pipeline_allows_non_critical_stage_failure(monkeypatch):
    db = DummyDB()

    monkeypatch.setattr(pipeline, "SessionLocal", DummySessionFactory(db))
    monkeypatch.setattr(pipeline, "get_or_create_service_state", lambda _db: db.state)
    monkeypatch.setattr(pipeline, "ingest_from_miniflux", lambda _db: {"inserted": 1, "inserted_article_ids": [1], "processed_entry_ids": [10]})
    monkeypatch.setattr(
        pipeline,
        "assign_articles_to_clusters",
        lambda _db: {"attached": 1, "touched_cluster_ids": [2], "new_articles_by_cluster": {2: []}},
    )
    monkeypatch.setattr(pipeline, "summarize_clusters", lambda _db, **kwargs: (_ for _ in ()).throw(RuntimeError("summary down")))
    monkeypatch.setattr(pipeline, "rank_clusters", lambda _db, **kwargs: None)
    monkeypatch.setattr(pipeline, "ingest_social_context", lambda _db, **kwargs: {"clusters": 0, "items": 0})
    monkeypatch.setattr(
        pipeline,
        "MeiliService",
        lambda: SimpleNamespace(index_from_db=lambda _db, **kwargs: {"articles": 1, "clusters": 1}),
    )

    result = pipeline.run_pipeline()

    assert result["ingested"] == 1
    assert db.state.last_pipeline_success is True
    assert db.state.last_pipeline_stage == "complete_warn"
    assert "summarize_failed" in (db.state.last_pipeline_error or "")
