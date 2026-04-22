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


def test_search_prioritizes_clusters_with_matching_articles(monkeypatch):
    def fake_request(self, method, path, payload=None):
        if path == "/indexes/clusters/search":
            return {
                "hits": [
                    {"cluster_id": 1, "score": 0.4, "importance_score": 0.4, "freshness_score": 0.4},
                    {"cluster_id": 2, "score": 0.6, "importance_score": 0.5, "freshness_score": 0.5},
                ]
            }
        return {"hits": [{"cluster_id": 1}, {"cluster_id": 1}]}

    monkeypatch.setattr(MeiliService, "_request", fake_request)
    svc = MeiliService()
    result = svc.search("flood")

    assert result["clusters"][0]["cluster_id"] == 1
