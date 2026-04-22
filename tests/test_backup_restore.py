import app.services.backup_restore as backup_restore


def test_validate_payload_rejects_wrong_version():
    payload = {"schema_version": 99, "data": {}}
    try:
        backup_restore._validate_payload(payload)
    except backup_restore.BackupValidationError as exc:
        assert "Unsupported backup" in str(exc)


def test_restore_requires_confirmation(monkeypatch):
    payload = {
        "schema_version": backup_restore.BACKUP_SCHEMA_VERSION,
        "created_at": "2026-01-01T00:00:00+00:00",
        "includes_articles": False,
        "data": {
            "app_settings": [],
            "sources": [],
            "feed_fetch_states": [],
            "clusters": [],
            "cluster_events": [],
            "articles": [],
        },
    }

    class DummyDB:
        def begin_nested(self):
            class _C:
                def __enter__(self):
                    return None

                def __exit__(self, exc_type, exc, tb):
                    return False

            return _C()

        def commit(self):
            return None

    try:
        backup_restore.restore_backup(DummyDB(), payload, confirm_overwrite=False)
    except backup_restore.BackupValidationError as exc:
        assert "confirmation" in str(exc)


def test_validate_payload_accepts_legacy_without_social_items():
    payload = {
        "schema_version": backup_restore.BACKUP_SCHEMA_VERSION,
        "created_at": "2026-01-01T00:00:00+00:00",
        "includes_articles": False,
        "data": {
            "app_settings": [],
            "sources": [],
            "feed_fetch_states": [],
            "clusters": [],
            "cluster_events": [],
            "articles": [],
        },
    }

    parsed = backup_restore._validate_payload(payload)

    assert parsed.data["social_items"] == []


def test_validate_payload_backfills_legacy_source_metadata():
    payload = {
        "schema_version": backup_restore.BACKUP_SCHEMA_VERSION,
        "created_at": "2026-01-01T00:00:00+00:00",
        "includes_articles": False,
        "data": {
            "app_settings": [],
            "sources": [
                {
                    "name": "Reuters World",
                    "feed_url": "https://feeds.reuters.com/Reuters/worldNews",
                }
            ],
            "feed_fetch_states": [],
            "clusters": [],
            "cluster_events": [],
            "articles": [],
        },
    }

    parsed = backup_restore._validate_payload(payload)
    source = parsed.data["sources"][0]

    assert source["source_type"] == "wire"
    assert source["topic"] == "general"
    assert source["geography"] == "global"


def test_validate_payload_backfills_legacy_source_metadata():
    payload = {
        "schema_version": backup_restore.BACKUP_SCHEMA_VERSION,
        "created_at": "2026-01-01T00:00:00+00:00",
        "includes_articles": False,
        "data": {
            "app_settings": [],
            "sources": [
                {
                    "name": "Reuters World",
                    "feed_url": "https://feeds.reuters.com/Reuters/worldNews",
                }
            ],
            "feed_fetch_states": [],
            "clusters": [],
            "cluster_events": [],
            "articles": [],
        },
    }

    parsed = backup_restore._validate_payload(payload)
    source = parsed.data["sources"][0]

    assert source["source_type"] == "wire"
    assert source["topic"] == "general"
    assert source["geography"] == "global"
