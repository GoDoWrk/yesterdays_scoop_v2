from app.services.text import jaccard_similarity, normalize_url, tokenize


def test_normalize_url_removes_utm():
    assert normalize_url("https://example.com/a?utm_source=x&id=1") == "https://example.com/a?id=1"


def test_tokenize_and_similarity():
    a = set(tokenize("Global markets rally on inflation cooldown"))
    b = set(tokenize("Inflation cooldown pushes global market rally"))
    assert jaccard_similarity(a, b) > 0.4
