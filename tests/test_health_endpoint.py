from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import app.main as main


class DummyConn:
    def execute(self, _query):
        return 1


class DummyEngine:
    def connect(self):
        class _Ctx:
            def __enter__(self):
                return DummyConn()

            def __exit__(self, exc_type, exc, tb):
                return False

        return _Ctx()


class DummySession:
    def __init__(self, _engine):
        self.calls = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def scalar(self, _query):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(
                miniflux_bootstrap_completed=True,
                miniflux_last_attempt_at=datetime.now(timezone.utc),
                miniflux_retry_count=1,
            )
        return SimpleNamespace(
            id=1,
            scheduler_last_tick_at=datetime.now(timezone.utc),
            worker_last_heartbeat_at=datetime.now(timezone.utc),
            last_pipeline_started_at=datetime.now(timezone.utc),
            last_pipeline_finished_at=datetime.now(timezone.utc),
            last_pipeline_success=True,
            last_pipeline_stage="complete",
            last_pipeline_error=None,
        )


def test_health_reports_worker_and_scheduler(monkeypatch):
    monkeypatch.setattr(main, "engine", DummyEngine())
    monkeypatch.setattr(main, "Session", DummySession)
    monkeypatch.setattr(main, "MinifluxClient", lambda: SimpleNamespace(health=lambda: True))
    monkeypatch.setattr(main, "MeiliService", lambda: SimpleNamespace(health=lambda: True))
    monkeypatch.setattr(main, "LLMService", lambda: SimpleNamespace(ollama_health=lambda: True))
    monkeypatch.setattr(
        main,
        "celery_app",
        SimpleNamespace(control=SimpleNamespace(inspect=lambda timeout=1.0: SimpleNamespace(ping=lambda: {"worker": {"ok": "pong"}}))),
    )

    result = main.health()

    assert result["status"] == "ok"
    assert result["scheduler_healthy"] is True
    assert result["worker_healthy"] is True
    assert result["last_pipeline_stage"] == "complete"
    assert result["last_pipeline_error"] is None
    assert result["degraded_reasons"] == []


def test_health_degraded_when_scheduler_stale(monkeypatch):
    stale_state = SimpleNamespace(
        id=1,
        scheduler_last_tick_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        worker_last_heartbeat_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        last_pipeline_started_at=None,
        last_pipeline_finished_at=None,
        last_pipeline_success=None,
        last_pipeline_stage=None,
        last_pipeline_error="boom",
    )

    class StaleSession(DummySession):
        def scalar(self, _query):
            self.calls += 1
            if self.calls == 1:
                return SimpleNamespace(
                    miniflux_bootstrap_completed=True,
                    miniflux_last_attempt_at=datetime.now(timezone.utc),
                    miniflux_retry_count=1,
                )
            return stale_state

    monkeypatch.setattr(main, "engine", DummyEngine())
    monkeypatch.setattr(main, "Session", StaleSession)
    monkeypatch.setattr(main, "MinifluxClient", lambda: SimpleNamespace(health=lambda: True))
    monkeypatch.setattr(main, "MeiliService", lambda: SimpleNamespace(health=lambda: True))
    monkeypatch.setattr(main, "LLMService", lambda: SimpleNamespace(ollama_health=lambda: True))
    monkeypatch.setattr(
        main,
        "celery_app",
        SimpleNamespace(control=SimpleNamespace(inspect=lambda timeout=1.0: SimpleNamespace(ping=lambda: {"worker": {"ok": "pong"}}))),
    )

    result = main.health()
    assert result["status"] == "degraded"
    assert result["scheduler_healthy"] is False
    assert "scheduler_unhealthy" in result["degraded_reasons"]


def test_health_reports_optional_service_outages(monkeypatch):
    monkeypatch.setattr(main, "engine", DummyEngine())
    monkeypatch.setattr(main, "Session", DummySession)
    monkeypatch.setattr(main, "MinifluxClient", lambda: SimpleNamespace(health=lambda: True))
    monkeypatch.setattr(main, "MeiliService", lambda: SimpleNamespace(health=lambda: False))
    monkeypatch.setattr(main, "LLMService", lambda: SimpleNamespace(ollama_health=lambda: False))
    monkeypatch.setattr(
        main,
        "celery_app",
        SimpleNamespace(control=SimpleNamespace(inspect=lambda timeout=1.0: SimpleNamespace(ping=lambda: {"worker": {"ok": "pong"}}))),
    )

    result = main.health()

    assert result["status"] == "degraded"
    assert "meilisearch_unreachable" in result["degraded_reasons"]
    assert "ollama_unreachable" in result["degraded_reasons"]
