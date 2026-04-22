from datetime import datetime

from app.services.miniflux_client import MinifluxClient


class DummyResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8") if text else (b"{}" if payload is not None else b"")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


class DummyClient:
    def __init__(self, *args, **kwargs):
        self.created_feeds = []
        self.api_key_created = False
        self.entry_statuses = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, *args, **kwargs):
        if url.endswith("/v1/me"):
            return DummyResponse({"username": "admin"})
        if url.endswith("/v1/categories"):
            return DummyResponse([])
        if url.endswith("/v1/entries"):
            params = kwargs.get("params", {})
            self.entry_statuses.append(params.get("status"))
            return DummyResponse(
                {
                    "entries": [
                        {
                            "id": 10,
                            "title": "Sample",
                            "url": "https://example.com/a",
                            "content": "hello",
                            "summary": "sum",
                            "author": "A",
                            "published_at": "2026-04-20T00:00:00Z",
                            "feed": {"id": 2, "title": "Feed"},
                        }
                    ]
                }
            )
        return DummyResponse({})

    def post(self, url, *args, **kwargs):
        if url.endswith("/v1/api_keys"):
            self.api_key_created = True
            return DummyResponse({"api_key": "generated-token"}, status_code=201)
        if url.endswith("/v1/categories"):
            return DummyResponse({"id": 55}, status_code=201)
        if url.endswith("/v1/feeds"):
            self.created_feeds.append(kwargs.get("json", {}).get("feed_url"))
            return DummyResponse({}, status_code=201)
        if url.endswith("/v1/feeds/import"):
            return DummyResponse({"created": 1, "existing": 0, "invalid": 0}, status_code=201)
        return DummyResponse({})

    def put(self, *args, **kwargs):
        return DummyResponse({}, status_code=200)


def test_get_entries_parses_payload(monkeypatch):
    import app.services.miniflux_client as mod

    client_instance = DummyClient()
    monkeypatch.setattr(mod.httpx, "Client", lambda *args, **kwargs: client_instance)
    client = MinifluxClient(api_key="token")
    entries = client.get_entries(limit=1)

    assert len(entries) == 1
    assert entries[0].id == 10
    assert entries[0].feed_title == "Feed"
    assert isinstance(entries[0].published_at, datetime)
    assert client_instance.entry_statuses == ["unread", "read"]


def test_basic_auth_bootstrap_path_and_api_key_creation(monkeypatch):
    import app.services.miniflux_client as mod

    monkeypatch.setattr(mod.httpx, "Client", DummyClient)
    client = MinifluxClient(api_key=None)
    result = client.bootstrap([{"name": "Feed A", "feed_url": "https://a.example/rss"}])

    assert result["ok"] is True
    assert result["token"] == "generated-token"
    assert result["feed_result"]["created"] == 1


def test_bootstrap_is_idempotent_for_existing_feeds(monkeypatch):
    import app.services.miniflux_client as mod

    class IdempotentClient(DummyClient):
        def post(self, url, *args, **kwargs):
            if url.endswith("/v1/feeds"):
                return DummyResponse({}, status_code=409)
            return super().post(url, *args, **kwargs)

    monkeypatch.setattr(mod.httpx, "Client", IdempotentClient)
    client = MinifluxClient(api_key="token")
    result = client.bootstrap_feeds([{"name": "Feed A", "feed_url": "https://a.example/rss"}])

    assert result["created"] == 0
    assert result["skipped"] == 1


def test_import_opml_supports_bulk_parsing(monkeypatch):
    import app.services.miniflux_client as mod

    monkeypatch.setattr(mod.httpx, "Client", DummyClient)
    client = MinifluxClient(api_key="token")
    result = client.import_opml("""<?xml version="1.0"?><opml><body><outline text="A" xmlUrl="https://example.com/rss"/></body></opml>""")

    assert result["created"] >= 1


def test_parse_opml_urls_dedupes_and_validates(monkeypatch):
    client = MinifluxClient(api_key="token")
    urls = client.parse_opml_urls("""<?xml version="1.0"?><opml><body><outline text="A" xmlUrl="https://example.com/rss"/><outline text="A2" xmlUrl="https://example.com/rss"/><outline text="bad" xmlUrl="ftp://example.com/rss"/></body></opml>""")
    assert len(urls) == 1
