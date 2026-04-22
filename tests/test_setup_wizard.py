from types import SimpleNamespace

import app.main as main
from starlette.requests import Request


class DummyDB:
    def __init__(self, settings, admin_user=None):
        self.settings = settings
        self.admin_user = admin_user
        self.commits = 0
        self.added = []
        self.calls = 0

    def scalar(self, _query):
        self.calls += 1
        if self.calls == 1:
            return self.settings
        return self.admin_user

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1


def test_setup_step2_blocks_if_database_check_fails(monkeypatch):
    settings = SimpleNamespace(setup_completed=False, setup_last_step=1)
    db = DummyDB(settings=settings)
    monkeypatch.setattr(main, "health", lambda: {"database": False})

    response = main.setup_wizard_submit(step=2, request=object(), db=db)

    assert response.status_code == 303
    assert "error=Database+must+be+healthy" in response.headers["location"]


def test_setup_step1_advances_to_step2():
    settings = SimpleNamespace(setup_completed=False, setup_last_step=1)
    db = DummyDB(settings=settings)

    response = main.setup_wizard_submit(step=1, request=object(), db=db)

    assert response.status_code == 303
    assert response.headers["location"] == "/setup/2"


def test_setup_step3_creates_admin_for_first_run(monkeypatch):
    settings = SimpleNamespace(setup_completed=False, setup_last_step=2)
    db = DummyDB(settings=settings, admin_user=None)
    monkeypatch.setattr(main, "hash_password", lambda raw: f"hashed::{raw}")

    response = main.setup_wizard_submit(
        step=3,
        request=object(),
        db=db,
        admin_username="owner",
        admin_password="supersecret",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/setup/4"
    assert len(db.added) == 1
    assert db.added[0].username == "owner"
    assert db.added[0].hashed_password == "hashed::supersecret"


def test_setup_step3_existing_admin_accepts_valid_current_password(monkeypatch):
    settings = SimpleNamespace(setup_completed=False, setup_last_step=2)
    admin_user = SimpleNamespace(username="admin", hashed_password="hashed", is_admin=True)
    db = DummyDB(settings=settings, admin_user=admin_user)
    monkeypatch.setattr(main, "verify_password", lambda raw, hashed: raw == "correct" and hashed == "hashed")

    response = main.setup_wizard_submit(
        step=3,
        request=object(),
        db=db,
        admin_username="admin",
        admin_password="",
        current_password="correct",
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/setup/4"


def test_setup_step3_existing_admin_rejects_invalid_current_password(monkeypatch):
    settings = SimpleNamespace(setup_completed=False, setup_last_step=2)
    admin_user = SimpleNamespace(username="admin", hashed_password="hashed", is_admin=True)
    db = DummyDB(settings=settings, admin_user=admin_user)
    monkeypatch.setattr(main, "verify_password", lambda _raw, _hashed: False)

    response = main.setup_wizard_submit(
        step=3,
        request=object(),
        db=db,
        admin_username="admin",
        admin_password="",
        current_password="wrong",
    )

    assert response.status_code == 303
    assert "Current+password+is+incorrect" in response.headers["location"]


def test_setup_wizard_renders_step_one_template_without_crashing(monkeypatch):
    settings = SimpleNamespace(setup_completed=False, setup_last_step=1)
    db = DummyDB(settings=settings, admin_user=None)
    monkeypatch.setattr(main, "health", lambda: {"database": True})

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/setup/1",
        "raw_path": b"/setup/1",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    request = Request(scope)

    response = main.setup_wizard(step=1, request=request, db=db)

    assert response.status_code == 200


def test_setup_wizard_returns_fallback_html_when_render_fails(monkeypatch):
    settings = SimpleNamespace(setup_completed=False, setup_last_step=1)
    db = DummyDB(settings=settings, admin_user=None)
    monkeypatch.setattr(main, "health", lambda: {"database": True})
    monkeypatch.setattr(main, "_template_response", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/setup/1",
        "raw_path": b"/setup/1",
        "query_string": b"",
        "headers": [],
        "client": ("testclient", 123),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    request = Request(scope)

    response = main.setup_wizard(step=1, request=request, db=db)

    assert response.status_code == 200
    assert "Setup temporarily unavailable" in response.body.decode("utf-8")
