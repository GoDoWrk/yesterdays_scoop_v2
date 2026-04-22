from types import SimpleNamespace

import app.main as main
import app.services.ingestion as ingestion


class SetupDummyDB:
    def __init__(self):
        self.settings = SimpleNamespace(
            setup_completed=False,
            setup_last_step=1,
            region="global",
            local_relevance_preference="medium",
            topics=["world"],
            source_preset="balanced",
            llm_provider="ollama",
            miniflux_base_url="http://miniflux:8080",
            miniflux_admin_username="admin",
            miniflux_admin_password="admin123",
            ollama_base_url="http://ollama:11434",
            ollama_chat_model="llama3.1:8b",
            ollama_embed_model="nomic-embed-text",
            openai_api_key=None,
            openai_model="gpt-4.1-mini",
            openai_fallback_enabled=True,
            enable_social_context=False,
            enable_reddit_context=True,
            enable_x_context=False,
            miniflux_bootstrap_completed=False,
        )
        self.admin_user = None
        self.calls = 0
        self.added = []
        self.commits = 0

    def scalar(self, _query):
        query_text = str(_query)
        if "FROM app_settings" in query_text:
            return self.settings
        if "FROM users" in query_text:
            return self.admin_user
        return None

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "is_admin", False):
            self.admin_user = obj

    def commit(self):
        self.commits += 1


class IngestDummyDB:
    def __init__(self):
        self.added = []
        self._existing = None

    def scalar(self, *args, **kwargs):
        return self._existing

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        pass


class DummyEntry:
    id = 101
    feed_id = 5
    feed_title = "Feed"
    title = "Hello"
    url = "https://example.com/news"
    content = "Body"
    summary = "Summary"
    author = "Reporter"
    published_at = None


class DummyMinifluxClient:
    def __init__(self):
        self.kwargs = {}
        self.marked = []

    def get_entries(self, **kwargs):
        self.kwargs = kwargs
        return [DummyEntry()]

    def mark_entries_read(self, ids):
        self.marked.extend(ids)


def test_fresh_install_smoke_setup_and_admin_flow(monkeypatch):
    db = SetupDummyDB()
    monkeypatch.setattr(main, "health", lambda: {"database": True})
    monkeypatch.setattr(main, "verify_password", lambda raw, _hashed: raw == "adminpass123")
    monkeypatch.setattr(main, "hash_password", lambda raw: f"hashed::{raw}")
    monkeypatch.setattr(main.retry_miniflux_bootstrap_task, "delay", lambda: None)
    monkeypatch.setattr(main.run_pipeline_task, "delay", lambda: None)

    assert main.setup_wizard_submit(step=2, request=object(), db=db).headers["location"] == "/setup/3"
    step3_create = main.setup_wizard_submit(
        step=3,
        request=object(),
        db=db,
        admin_username="admin",
        admin_password="adminpass123",
    )
    assert step3_create.headers["location"] == "/setup/4"
    assert db.admin_user is not None
    assert db.admin_user.hashed_password == "hashed::adminpass123"

    step3_confirm = main.setup_wizard_submit(
        step=3,
        request=object(),
        db=db,
        admin_username="admin",
        admin_password="",
        current_password="adminpass123",
    )
    assert step3_confirm.headers["location"] == "/setup/4"

    assert (
        main.setup_wizard_submit(
            step=4,
            request=object(),
            db=db,
            region="global",
            local_relevance_preference="medium",
            topics="world,technology",
        ).headers["location"]
        == "/setup/5"
    )
    assert (
        main.setup_wizard_submit(
            step=5,
            request=object(),
            db=db,
            source_preset="balanced",
        ).headers["location"]
        == "/setup/6"
    )
    assert (
        main.setup_wizard_submit(
            step=6,
            request=object(),
            db=db,
            llm_provider="ollama",
            miniflux_base_url="http://miniflux:8080",
            miniflux_admin_username="admin",
            miniflux_admin_password="admin123",
            ollama_base_url="http://ollama:11434",
            ollama_chat_model="llama3.1:8b",
            ollama_embed_model="nomic-embed-text",
            openai_api_key="",
            openai_model="gpt-4.1-mini",
            openai_fallback_enabled=True,
            test_connection=False,
        ).headers["location"]
        == "/setup/7"
    )
    assert (
        main.setup_wizard_submit(
            step=7,
            request=object(),
            db=db,
            enable_social_context=False,
            enable_reddit_context=True,
            enable_x_context=False,
        ).headers["location"]
        == "/setup/8"
    )
    assert main.setup_wizard_submit(step=8, request=object(), db=db).headers["location"] == "/onboarding"
    assert db.settings.setup_completed is True


def test_fresh_install_smoke_ingest_uses_valid_miniflux_statuses(monkeypatch):
    db = IngestDummyDB()
    client = DummyMinifluxClient()

    monkeypatch.setattr(ingestion, "MinifluxClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(ingestion, "_last_seen_miniflux_entry_id", lambda _db: 77)

    result = ingestion.ingest_from_miniflux(db, limit=20)

    assert result["inserted"] == 1
    assert result["processed_entry_ids"] == [101]
    assert client.kwargs["statuses"] == ("unread", "read")
