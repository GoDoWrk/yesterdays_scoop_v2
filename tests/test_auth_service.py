from types import SimpleNamespace

import app.services.auth as auth


class DummyDB:
    def __init__(self, user):
        self.user = user

    def scalar(self, _query):
        return self.user


def test_authenticate_user_accepts_valid_password():
    user = SimpleNamespace(is_active=True, hashed_password="hashed")
    db = DummyDB(user)
    original = auth.verify_password
    auth.verify_password = lambda password, _hashed: password == "secret-123"
    try:
        found = auth.authenticate_user(db, username="admin", password="secret-123")
    finally:
        auth.verify_password = original

    assert found is user


def test_authenticate_user_rejects_invalid_password():
    user = SimpleNamespace(is_active=True, hashed_password="hashed")
    db = DummyDB(user)
    original = auth.verify_password
    auth.verify_password = lambda password, _hashed: password == "secret-123"
    try:
        found = auth.authenticate_user(db, username="admin", password="wrong")
    finally:
        auth.verify_password = original

    assert found is None


def test_require_admin_rejects_non_admin_user():
    user = SimpleNamespace(is_admin=False)
    try:
        auth.require_admin(user)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 403
        return
    raise AssertionError("expected require_admin to reject non-admin users")


def test_login_submit_sets_session_cookie(monkeypatch):
    import app.main as main

    user = SimpleNamespace(username="owner")
    monkeypatch.setattr(main, "authenticate_user", lambda db, username, password: user)

    class DummyManager:
        cookie_name = "yscoop_session"

        @staticmethod
        def create_access_token(data):
            return f"token::{data['sub']}"

        @staticmethod
        def set_cookie(response, token):
            response.set_cookie("yscoop_session", token)

    monkeypatch.setattr(main, "manager", DummyManager())

    response = main.login_submit(db=object(), username="owner", password="secret", next_url="/onboarding")

    assert response.status_code == 303
    assert response.headers["location"] == "/onboarding"
    assert "yscoop_session=" in response.headers.get("set-cookie", "")


def test_login_submit_redirects_on_invalid_credentials(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "authenticate_user", lambda db, username, password: None)

    response = main.login_submit(db=object(), username="owner", password="bad", next_url="/onboarding")

    assert response.status_code == 303
    assert response.headers["location"].startswith("/login?error=Invalid+username+or+password")


def test_logout_submit_clears_session_cookie(monkeypatch):
    import app.main as main

    monkeypatch.setattr(main, "manager", SimpleNamespace(cookie_name="yscoop_session"))

    response = main.logout_submit()

    assert response.status_code == 303
    assert response.headers["location"] == "/login?ok=Logged+out"
    assert "yscoop_session=" in response.headers.get("set-cookie", "")
