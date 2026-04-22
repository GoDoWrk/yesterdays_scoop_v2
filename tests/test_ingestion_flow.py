import app.services.ingestion as ingestion


class DummyDB:
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


class DummyClient:
    def __init__(self):
        self.marked = []

    def get_entries(self, **kwargs):
        self.kwargs = kwargs
        return [DummyEntry()]

    def mark_entries_read(self, ids):
        self.marked.extend(ids)


def test_ingestion_marks_processed_entries(monkeypatch):
    db = DummyDB()
    client = DummyClient()

    monkeypatch.setattr(ingestion, "MinifluxClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(ingestion, "_last_seen_miniflux_entry_id", lambda _db: 77)

    result = ingestion.ingest_from_miniflux(db, limit=20)

    assert result["inserted"] == 1
    assert result["processed_entry_ids"] == [101]
    assert client.kwargs["after_entry_id"] == 77
    assert client.marked == [101]


def test_ingestion_skips_existing_articles(monkeypatch):
    db = DummyDB()
    db._existing = 99
    client = DummyClient()

    monkeypatch.setattr(ingestion, "MinifluxClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(ingestion, "_last_seen_miniflux_entry_id", lambda _db: 100)

    result = ingestion.ingest_from_miniflux(db, limit=20)

    assert result["inserted"] == 0
    assert result["processed_entry_ids"] == [101]
    assert client.marked == [101]
