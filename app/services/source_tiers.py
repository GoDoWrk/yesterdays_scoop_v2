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

TIER_WEIGHTS: dict[int, float] = {1: 1.0, 2: 0.8, 3: 0.6}
SOURCE_TYPE_WEIGHTS: dict[str, float] = {
    "wire": 1.0,
    "official": 0.95,
    "major_outlet": 0.88,
    "analysis": 0.82,
    "regional": 0.76,
    "local": 0.72,
    "niche": 0.74,
    "aggregator": 0.62,
    "social": 0.5,
}


def source_tier(source_name: str | None) -> int:
    if not source_name:
        return 3
    name = source_name.strip().lower()
    for tier, labels in SOURCE_TIERS.items():
        if any(label in name for label in labels):
            return tier
    return 3


def source_weight(source_name: str | None, *, source_type: str | None = None, tier_override: int | None = None, priority_weight: float | None = None) -> float:
    tier = tier_override or source_tier(source_name)
    tier_base = TIER_WEIGHTS.get(tier, 0.55)
    type_mult = SOURCE_TYPE_WEIGHTS.get((source_type or "").strip().lower(), 0.75)
    editorial_weight = priority_weight if priority_weight is not None else 1.0
    return min(1.2, max(0.25, tier_base * type_mult * editorial_weight))
