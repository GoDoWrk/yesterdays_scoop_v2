import app.main as main


class DummyDB:
    def __init__(self, values):
        self.values = list(values)

    def scalar(self, _query):
        return self.values.pop(0)


def test_dashboard_metrics_counts():
    db = DummyDB([100, 12, 3, 20, 2, 9])
    metrics = main._dashboard_metrics(db)

    assert metrics["total_articles"] == 100
    assert metrics["total_clusters"] == 12
    assert metrics["articles_1h"] == 3
    assert metrics["articles_24h"] == 20
    assert metrics["clusters_1h"] == 2
    assert metrics["clusters_24h"] == 9
