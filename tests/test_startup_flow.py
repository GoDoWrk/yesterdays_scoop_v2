from types import SimpleNamespace

import app.main as main


class DummySession:
    def __init__(self, _engine):
        self.entered = False

    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_startup_runs_migrations_bootstrap_and_meili(monkeypatch):
    calls = []

    monkeypatch.setattr(main, "run_migrations", lambda: calls.append("migrations"))
    monkeypatch.setattr(main, "engine", object())
    monkeypatch.setattr(main, "Session", DummySession)
    monkeypatch.setattr(main, "ensure_app_settings", lambda _db: None)
    monkeypatch.setattr(main, "bootstrap_data", lambda _db: calls.append("bootstrap"))
    monkeypatch.setattr(
        main,
        "MeiliService",
        lambda: SimpleNamespace(bootstrap_indexes=lambda: calls.append("meili_bootstrap")),
    )

    main.startup()

    assert calls == ["migrations", "bootstrap", "meili_bootstrap"]


def test_startup_stops_cleanly_when_migrations_fail(monkeypatch):
    calls = []

    def _boom():
        raise RuntimeError("migration failure")

    monkeypatch.setattr(main, "run_migrations", _boom)
    monkeypatch.setattr(main, "engine", object())
    monkeypatch.setattr(main, "Session", DummySession)
    monkeypatch.setattr(main, "ensure_app_settings", lambda _db: None)
    monkeypatch.setattr(main, "bootstrap_data", lambda _db: calls.append("bootstrap"))
    monkeypatch.setattr(
        main,
        "MeiliService",
        lambda: SimpleNamespace(bootstrap_indexes=lambda: calls.append("meili_bootstrap")),
    )

    main.startup()

    assert calls == []
