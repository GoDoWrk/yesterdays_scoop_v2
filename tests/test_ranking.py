from app.models import Cluster
from app.services.ranking import _cluster_state


def test_cluster_state_major_for_high_importance():
    cluster = Cluster(
        title="t",
        slug="s",
        importance_score=0.8,
        corroboration_count=6,
        freshness_score=0.8,
        velocity_score=0.5,
        staleness_decay=1.0,
    )
    assert _cluster_state(cluster) == "major"


def test_cluster_state_archived_when_stale():
    cluster = Cluster(
        title="t",
        slug="s",
        importance_score=0.2,
        corroboration_count=1,
        freshness_score=0.1,
        velocity_score=0.0,
        staleness_decay=0.2,
    )
    assert _cluster_state(cluster) == "archived"
