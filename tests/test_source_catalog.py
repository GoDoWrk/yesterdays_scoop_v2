from app.services.source_catalog import DEFAULT_SOURCE_CATALOG, default_poll_frequency_for_source, infer_source_metadata


def test_default_catalog_is_large_and_layered():
    assert len(DEFAULT_SOURCE_CATALOG) >= 35
    source_types = {s.get("source_type") for s in DEFAULT_SOURCE_CATALOG}
    for required in {"wire", "major_outlet", "analysis", "niche", "local", "aggregator"}:
        assert required in source_types


def test_poll_frequency_by_source_type():
    assert default_poll_frequency_for_source(source_type="wire", tier=1) < default_poll_frequency_for_source(source_type="analysis", tier=2)


def test_infer_source_metadata_handles_google_and_local():
    google = infer_source_metadata("Google News Politics", "https://news.google.com/rss")
    assert google["source_type"] == "aggregator"

    local = infer_source_metadata("Arizona Republic", "https://www.azcentral.com/rss/news/")
    assert local["source_type"] == "local"
