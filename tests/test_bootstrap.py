from types import SimpleNamespace

import app.services.bootstrap as bootstrap


class DummyDB:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_bootstrap_skips_default_admin_when_setup_incomplete(monkeypatch):
    db = DummyDB()
    calls = []
    settings = SimpleNamespace(setup_completed=False)

    monkeypatch.setattr(bootstrap, "ensure_app_settings", lambda _db: settings)
    monkeypatch.setattr(bootstrap, "_ensure_default_admin", lambda _db: calls.append("admin"))
    monkeypatch.setattr(bootstrap, "seed_source_registry", lambda _db: calls.append("seed"))
    monkeypatch.setattr(bootstrap, "attempt_miniflux_bootstrap", lambda *_args, **_kwargs: calls.append("miniflux"))

    bootstrap.bootstrap_data(db)

    assert calls == []


def test_bootstrap_runs_admin_and_services_when_setup_completed(monkeypatch):
    db = DummyDB()
    calls = []
    settings = SimpleNamespace(setup_completed=True)

    monkeypatch.setattr(bootstrap, "ensure_app_settings", lambda _db: settings)
    monkeypatch.setattr(bootstrap, "_ensure_default_admin", lambda _db: calls.append("admin"))
    monkeypatch.setattr(bootstrap, "seed_source_registry", lambda _db: calls.append("seed"))
    monkeypatch.setattr(bootstrap, "attempt_miniflux_bootstrap", lambda *_args, **_kwargs: calls.append("miniflux"))

    bootstrap.bootstrap_data(db)

    assert calls == ["admin", "seed", "miniflux"]
