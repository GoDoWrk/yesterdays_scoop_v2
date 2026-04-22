from __future__ import annotations

SOURCE_TIERS: dict[int, set[str]] = {
    1: {"reuters", "associated press", "ap news", "ap"},
    2: {
        "cnn",
        "bbc",
        "npr",
        "new york times",
        "washington post",
        "wall street journal",
        "abc news",
        "cbs news",
        "nbc news",
        "pbs",
        "usa today",
    },
}

TIER_WEIGHTS: dict[int, float] = {1: 1.0, 2: 0.75, 3: 0.5}


def source_tier(source_name: str | None) -> int:
    if not source_name:
        return 3
    name = source_name.strip().lower()
    for tier, labels in SOURCE_TIERS.items():
        if any(label in name for label in labels):
            return tier
    return 3


def source_weight(source_name: str | None) -> float:
    return TIER_WEIGHTS[source_tier(source_name)]
