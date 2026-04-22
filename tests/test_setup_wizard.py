from types import SimpleNamespace

import app.main as main


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
