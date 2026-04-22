from app.services.meili import MeiliService


def test_search_queries_both_indexes(monkeypatch):
    calls = []

    def fake_request(self, method, path, payload=None):
        calls.append((method, path, payload))
        return {"hits": []}

    monkeypatch.setattr(MeiliService, "_request", fake_request)
    svc = MeiliService()
    svc.search("budget")

    assert any(path == "/indexes/clusters/search" for _, path, _ in calls)
    assert any(path == "/indexes/articles/search" for _, path, _ in calls)
