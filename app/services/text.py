import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "in",
    "to",
    "for",
    "on",
    "with",
    "at",
    "by",
    "from",
    "and",
}


def tokenize(text: str) -> list[str]:
    raw_tokens = re.findall(r"[a-zA-Z0-9']+", text.lower())
    return [t for t in raw_tokens if t not in STOPWORDS and len(t) > 2]


def normalize_url(url: str) -> str:
    parsed = urlparse(url)
    kept_params = {k: v for k, v in parse_qs(parsed.query).items() if not k.startswith("utm_")}
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            urlencode(kept_params, doseq=True),
            "",
        )
    )


def jaccard_similarity(tokens_a: set[str], tokens_b: set[str]) -> float:
    if not tokens_a or not tokens_b:
        return 0.0
    inter = len(tokens_a & tokens_b)
    union = len(tokens_a | tokens_b)
    return inter / union
