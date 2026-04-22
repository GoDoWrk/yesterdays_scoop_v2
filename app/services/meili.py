from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Article, Cluster
from app.services.retry import with_retries
from app.services.runtime_config import get_runtime_overrides

logger = logging.getLogger(__name__)


class MeiliService:
    def __init__(self) -> None:
        settings = get_settings()
        overrides = get_runtime_overrides()
        self.enabled = bool(settings.meili_url)
        self.url = (overrides.get("meili_url") or settings.meili_url).rstrip("/")
        self.api_key = overrides.get("meili_master_key") or settings.meili_master_key

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _request(self, method: str, path: str, payload: dict | list | None = None) -> dict:
        import httpx

        def _send() -> dict:
            with httpx.Client(timeout=15.0) as client:
                res = client.request(method, f"{self.url}{path}", json=payload, headers=self._headers())
                res.raise_for_status()
                if res.content:
                    return res.json()
                return {}

        return with_retries(_send, attempts=3, base_delay_seconds=0.6, logger=logger, operation=f"meili {method} {path}")

    def health(self) -> bool:
        try:
            self._request("GET", "/health")
            return True
        except Exception:
            return False

    def bootstrap_indexes(self) -> None:
        try:
            self._request("PUT", "/indexes/articles", {"primaryKey": "id"})
        except Exception as exc:
            logger.warning("Meilisearch article index bootstrap warning: %s", exc)
        try:
            self._request("PUT", "/indexes/clusters", {"primaryKey": "id"})
        except Exception as exc:
            logger.warning("Meilisearch cluster index bootstrap warning: %s", exc)

        self._request("PATCH", "/indexes/articles/settings", {
            "searchableAttributes": ["title", "summary", "source_name", "extracted_text"],
            "filterableAttributes": ["published_at", "cluster_id", "source_name"],
            "sortableAttributes": ["published_at"],
        })
        self._request("PATCH", "/indexes/clusters/settings", {
            "searchableAttributes": ["title", "key_entities", "ai_summary", "why_it_matters", "what_changed", "cluster_state"],
            "filterableAttributes": ["updated_at", "source_count", "cluster_state", "seeking_confirmation"],
            "sortableAttributes": ["score", "importance_score", "velocity_score", "freshness_score", "updated_at"],
        })

    def index_from_db(self, db: Session, article_ids: list[int] | None = None, cluster_ids: list[int] | None = None) -> dict[str, int]:
        article_stmt = select(Article)
        if article_ids:
            article_stmt = article_stmt.where(Article.id.in_(article_ids))
        else:
            article_stmt = article_stmt.order_by(Article.id.desc()).limit(1000)

        cluster_stmt = select(Cluster)
        if cluster_ids:
            cluster_stmt = cluster_stmt.where(Cluster.id.in_(cluster_ids))
        else:
            cluster_stmt = cluster_stmt.order_by(Cluster.id.desc()).limit(1000)

        articles = db.scalars(article_stmt).all()
        clusters = db.scalars(cluster_stmt).all()

        article_docs = [
            {
                "id": f"a-{a.id}",
                "article_id": a.id,
                "cluster_id": a.cluster_id,
                "title": a.title,
                "summary": a.summary,
                "extracted_text": a.extracted_text,
                "source_name": a.source_name,
                "published_at": a.published_at.isoformat() if a.published_at else None,
                "url": a.canonical_url,
            }
            for a in articles
        ]
        cluster_docs = [
            {
                "id": f"c-{c.id}",
                "cluster_id": c.id,
                "slug": c.slug,
                "title": c.title,
                "ai_summary": c.ai_summary,
                "why_it_matters": c.why_it_matters,
                "key_entities": c.key_entities,
                "what_changed": c.what_changed,
                "freshness_score": c.freshness_score,
                "corroboration_count": c.corroboration_count,
                "source_count": c.source_count,
                "score": c.score,
                "importance_score": c.importance_score,
                "velocity_score": c.velocity_score,
                "local_relevance_score": c.local_relevance_score,
                "cluster_state": c.cluster_state,
                "seeking_confirmation": c.seeking_confirmation,
                "updated_at": c.updated_at.isoformat() if c.updated_at else None,
                "representative_url": c.representative_url,
            }
            for c in clusters
        ]

        if article_docs:
            self._request("POST", "/indexes/articles/documents", article_docs)
        if cluster_docs:
            self._request("POST", "/indexes/clusters/documents", cluster_docs)
        return {"articles": len(article_docs), "clusters": len(cluster_docs)}

    def search(self, query: str, limit: int = 20) -> dict:
        cluster_hits = self._request("POST", "/indexes/clusters/search", {
            "q": query,
            "limit": limit,
            "sort": ["score:desc", "freshness_score:desc", "updated_at:desc"],
            "attributesToHighlight": ["title", "ai_summary", "why_it_matters", "key_entities", "what_changed"],
            "matchingStrategy": "all",
        }).get("hits", [])
        article_hits = self._request("POST", "/indexes/articles/search", {
            "q": query,
            "limit": limit,
            "sort": ["published_at:desc"],
            "attributesToHighlight": ["title", "summary", "extracted_text", "source_name"],
            "matchingStrategy": "all",
        }).get("hits", [])

        # Cluster-first retrieval: boost clusters that also have matching articles.
        article_cluster_boost: dict[int, int] = {}
        for hit in article_hits:
            cluster_id = hit.get("cluster_id")
            if isinstance(cluster_id, int):
                article_cluster_boost[cluster_id] = article_cluster_boost.get(cluster_id, 0) + 1

        def _cluster_rank(hit: dict) -> tuple:
            cid = hit.get("cluster_id")
            return (
                article_cluster_boost.get(cid, 0),
                float(hit.get("score") or 0.0),
                float(hit.get("importance_score") or 0.0),
                float(hit.get("freshness_score") or 0.0),
            )

        cluster_hits = sorted(cluster_hits, key=_cluster_rank, reverse=True)
        return {"clusters": cluster_hits[:limit], "articles": article_hits[:limit]}
