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
