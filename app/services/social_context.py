from __future__ import annotations

from datetime import datetime, timedelta, timezone
import logging
import math

import httpx
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import AppSetting, Cluster, SocialItem
from app.services.text import jaccard_similarity, tokenize

logger = logging.getLogger(__name__)


def ingest_social_context(db: Session, cluster_ids: list[int] | None = None) -> dict[str, int]:
    app_settings = db.scalar(select(AppSetting).limit(1))
    settings = get_settings()

    enabled = (app_settings.enable_social_context if app_settings else settings.enable_social_context)
    if not enabled:
        return {"clusters": 0, "items": 0}

    max_items = (app_settings.social_max_items if app_settings else settings.social_max_items) or 8
    use_reddit = (app_settings.enable_reddit_context if app_settings else settings.enable_reddit_context)
    use_x = (app_settings.enable_x_context if app_settings else settings.enable_x_context)
    bearer = (app_settings.x_api_bearer_token if app_settings else settings.x_api_bearer_token) or ""

    stmt = select(Cluster)
    if cluster_ids:
        stmt = stmt.where(Cluster.id.in_(cluster_ids))
    clusters = db.scalars(stmt).all()

    touched = 0
    total_items = 0
    for cluster in clusters:
        queries = _queries_for_cluster(cluster)
        collected: list[dict] = []

        if use_reddit:
            try:
                collected.extend(_fetch_reddit(queries, max_items=max_items * 2))
            except Exception as exc:
                logger.warning("Social context reddit failed for cluster %s: %s", cluster.id, exc)

        if use_x and bearer:
            try:
                collected.extend(_fetch_x(queries, bearer=bearer, max_items=max_items * 2))
            except Exception as exc:
                logger.warning("Social context X failed for cluster %s: %s", cluster.id, exc)

        ranked = _rank_social_items(cluster, collected)[:max_items]

        db.execute(delete(SocialItem).where(SocialItem.cluster_id == cluster.id))
        for item in ranked:
            db.add(
                SocialItem(
                    cluster_id=cluster.id,
                    platform=item["platform"],
                    author=item.get("author"),
                    content=item["content"][:2800],
                    url=item["url"],
                    created_at=item["created_at"],
                    engagement=item.get("engagement", {}),
                    is_verified_source=bool(item.get("is_verified_source", False)),
                )
            )
        touched += 1
        total_items += len(ranked)

    db.commit()
    return {"clusters": touched, "items": total_items}


def split_social_sections(items: list[SocialItem]) -> tuple[list[SocialItem], list[SocialItem]]:
    official = [i for i in items if i.is_verified_source]
    public = [i for i in items if not i.is_verified_source]
    return official, public


def _queries_for_cluster(cluster: Cluster) -> list[str]:
    base = [cluster.title]
    if cluster.key_entities:
        base.extend(cluster.key_entities[:4])
    tokens = [t for t in tokenize(cluster.title) if len(t) > 3][:4]
    base.extend(tokens)
    # unique + concise queries
    seen = set()
    out = []
    for q in base:
        qq = (q or "").strip()
        if not qq:
            continue
        norm = qq.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(qq)
    return out[:6]


def _fetch_reddit(queries: list[str], *, max_items: int) -> list[dict]:
    items: list[dict] = []
    headers = {"User-Agent": "yesterdays-scoop/1.0"}
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)

    with httpx.Client(timeout=12.0, headers=headers) as client:
        for query in queries[:3]:
            r = client.get("https://www.reddit.com/search.json", params={"q": query, "sort": "new", "limit": 20})
            r.raise_for_status()
            children = (r.json().get("data") or {}).get("children") or []
            for child in children:
                data = child.get("data") or {}
                created = datetime.fromtimestamp(float(data.get("created_utc", 0)), tz=timezone.utc)
                if created < cutoff:
                    continue
                permalink = data.get("permalink") or ""
                url = f"https://reddit.com{permalink}" if permalink else (data.get("url") or "")
                items.append(
                    {
                        "platform": "reddit",
                        "author": data.get("author"),
                        "content": (data.get("title") or "") + " " + (data.get("selftext") or ""),
                        "url": url,
                        "created_at": created,
                        "engagement": {"score": int(data.get("score", 0)), "comments": int(data.get("num_comments", 0))},
                        "is_verified_source": False,
                    }
                )
                if len(items) >= max_items:
                    return items
    return items


def _fetch_x(queries: list[str], *, bearer: str, max_items: int) -> list[dict]:
    if not bearer:
        return []

    items: list[dict] = []
    headers = {"Authorization": f"Bearer {bearer}"}
    with httpx.Client(timeout=12.0, headers=headers) as client:
        for query in queries[:2]:
            r = client.get(
                "https://api.twitter.com/2/tweets/search/recent",
                params={
                    "query": query,
                    "max_results": 25,
                    "tweet.fields": "created_at,public_metrics,author_id",
                    "expansions": "author_id",
                    "user.fields": "name,username,verified",
                },
            )
            if r.status_code == 401:
                logger.warning("X connector unauthorized; disabling this run")
                return items
            r.raise_for_status()
            payload = r.json()
            users = {u.get("id"): u for u in (payload.get("includes") or {}).get("users", [])}
            for tw in payload.get("data", []):
                user = users.get(tw.get("author_id"), {})
                metrics = tw.get("public_metrics") or {}
                created_raw = tw.get("created_at")
                created = datetime.fromisoformat(created_raw.replace("Z", "+00:00")) if created_raw else datetime.now(timezone.utc)
                items.append(
                    {
                        "platform": "x",
                        "author": user.get("username") or user.get("name"),
                        "content": tw.get("text") or "",
                        "url": f"https://x.com/{user.get('username')}/status/{tw.get('id')}" if user.get("username") else "",
                        "created_at": created,
                        "engagement": {
                            "likes": int(metrics.get("like_count", 0)),
                            "retweets": int(metrics.get("retweet_count", 0)),
                            "replies": int(metrics.get("reply_count", 0)),
                        },
                        "is_verified_source": bool(user.get("verified", False)),
                    }
                )
                if len(items) >= max_items:
                    return items
    return items


def _rank_social_items(cluster: Cluster, items: list[dict]) -> list[dict]:
    now = datetime.now(timezone.utc)
    cluster_tokens = set(tokenize(f"{cluster.title} {' '.join(cluster.key_entities or [])}"))

    def score(item: dict) -> float:
        text_tokens = set(tokenize(item.get("content") or ""))
        relevance = jaccard_similarity(cluster_tokens, text_tokens)
        age_hours = max(0.0, (now - item["created_at"]).total_seconds() / 3600)
        recency = math.exp(-age_hours / 18)
        engagement = _engagement_score(item.get("engagement") or {})
        credibility = 1.0 if item.get("is_verified_source") else 0.0
        return relevance * 0.45 + recency * 0.25 + engagement * 0.2 + credibility * 0.1

    dedup = {}
    for item in items:
        url = item.get("url")
        if not url:
            continue
        if url not in dedup:
            dedup[url] = item
    ranked = sorted(dedup.values(), key=score, reverse=True)
    return ranked


def _engagement_score(payload: dict) -> float:
    total = 0
    for key in ["likes", "retweets", "replies", "comments", "score"]:
        total += int(payload.get(key, 0) or 0)
    return min(1.0, total / 5000.0)
