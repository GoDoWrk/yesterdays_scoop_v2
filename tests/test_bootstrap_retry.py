from types import SimpleNamespace

import app.services.bootstrap as bootstrap


class DummyDB:
    def __init__(self):
        self.commits = 0

    def commit(self):
        self.commits += 1


def test_attempt_bootstrap_updates_retry_and_error(monkeypatch):
    db = DummyDB()
    settings = SimpleNamespace(
        miniflux_bootstrap_completed=False,
        miniflux_bootstrap_error=None,
        miniflux_api_key=None,
        miniflux_last_attempt_at=None,
        miniflux_retry_count=0,
    )

    class FailingClient:
        def __init__(self, api_key=None):
            pass

        def bootstrap(self, _feeds):
            return {"ok": False, "error": "miniflux_unreachable"}

    monkeypatch.setattr(bootstrap, "MinifluxClient", FailingClient)
    ok = bootstrap.attempt_miniflux_bootstrap(db, app_settings=settings, reason="test")

    assert ok is False
    assert settings.miniflux_retry_count == 1
    assert settings.miniflux_bootstrap_error == "miniflux_unreachable"


def test_attempt_bootstrap_clears_error_on_success(monkeypatch):
    db = DummyDB()
    settings = SimpleNamespace(
        miniflux_bootstrap_completed=False,
        miniflux_bootstrap_error="previous",
        miniflux_api_key=None,
        miniflux_last_attempt_at=None,
        miniflux_retry_count=2,
    )

    class SuccessClient:
        def __init__(self, api_key=None):
            pass

        def bootstrap(self, _feeds):
            return {"ok": True, "token": "abc", "feed_result": {"created": 1, "skipped": 2}}

    monkeypatch.setattr(bootstrap, "MinifluxClient", SuccessClient)
    ok = bootstrap.attempt_miniflux_bootstrap(db, app_settings=settings, reason="test")

    assert ok is True
    assert settings.miniflux_bootstrap_completed is True
    assert settings.miniflux_bootstrap_error is None
    assert settings.miniflux_api_key == "abc"


def test_attempt_bootstrap_noop_when_already_complete(monkeypatch):
    db = DummyDB()
    settings = SimpleNamespace(
        miniflux_bootstrap_completed=True,
        miniflux_bootstrap_error=None,
        miniflux_api_key=None,
        miniflux_last_attempt_at=None,
        miniflux_retry_count=3,
    )

    monkeypatch.setattr(bootstrap, "MinifluxClient", lambda api_key=None: None)
    ok = bootstrap.attempt_miniflux_bootstrap(db, app_settings=settings, reason="test")

    assert ok is True
    assert settings.miniflux_retry_count == 3
