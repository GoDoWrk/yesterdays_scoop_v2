from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
from urllib.parse import urlparse

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Article, Cluster, ClusterEvent, Source
from app.services.llm import LLMService
from app.services.text import jaccard_similarity, tokenize


TIME_WINDOW = timedelta(hours=18)
MAX_CLUSTER_AGE = timedelta(hours=72)
TOKEN_SIMILARITY_THRESHOLD = 0.28
SEMANTIC_SIMILARITY_THRESHOLD = 0.82
HIGH_CONFIDENCE_SEMANTIC = 0.9
CLUSTER_MODEL = Cluster


def assign_articles_to_clusters(db: Session) -> dict:
    llm = LLMService()
    unclustered = db.scalars(select(Article).where(Article.cluster_id.is_(None)).order_by(Article.published_at.desc())).all()
    clusters = db.scalars(select(CLUSTER_MODEL)).all()

    attached = 0
    touched_cluster_ids: set[int] = set()
    new_articles_by_cluster: dict[int, list[dict[str, str | None]]] = {}
    for article in unclustered:
        if not article.embedding:
            article.embedding = llm.embed(f"{article.title}\n{(article.summary or '')[:500]}")

        article_tokens = set(article.normalized_tokens or tokenize(article.title))
        best_cluster = None
        best_score = -1.0

        for cluster in clusters:
            cluster_tokens = set(tokenize(cluster.title))
            lexical_similarity = jaccard_similarity(article_tokens, cluster_tokens)
            semantic_similarity = cosine_similarity(article.embedding or [], cluster.semantic_centroid or [])

            updated_ref = cluster.updated_at or datetime.now(timezone.utc)
            published_ref = article.published_at or datetime.now(timezone.utc)
            within_window = abs(updated_ref - published_ref) <= TIME_WINDOW
            cluster_is_fresh = (datetime.now(timezone.utc) - updated_ref) <= MAX_CLUSTER_AGE
            overlap = len(article_tokens & cluster_tokens)
            same_domain = _domain(article.canonical_url) == _domain(cluster.representative_url)
            is_duplicate_source = article.canonical_url in (cluster.source_urls or [])
            same_family = _has_same_outlet_family(db, cluster.id, article.source_name)

            is_match = (
                semantic_similarity >= HIGH_CONFIDENCE_SEMANTIC
                or (semantic_similarity >= SEMANTIC_SIMILARITY_THRESHOLD and lexical_similarity >= 0.12)
                or (lexical_similarity >= TOKEN_SIMILARITY_THRESHOLD and overlap >= 2)
            )
            score = semantic_similarity * 0.8 + lexical_similarity * 0.2 - (0.05 if same_domain else 0.0) - (0.08 if same_family else 0.0)

            if within_window and cluster_is_fresh and not is_duplicate_source and is_match and score > best_score:
                best_score = score
                best_cluster = cluster

        if best_cluster:
            article.cluster_id = best_cluster.id
            best_cluster.source_count += 1
            best_cluster.update_frequency += 1
            best_cluster.updated_at = datetime.now(timezone.utc)
            best_cluster.last_activity_at = article.published_at or datetime.now(timezone.utc)
            best_cluster.semantic_centroid = blend_vectors(best_cluster.semantic_centroid or [], article.embedding or [])
            db.add(
                ClusterEvent(
                    cluster_id=best_cluster.id,
                    event_type="article_attached",
                    details={"article_id": article.id, "semantic_score": best_score},
                )
            )
            attached += 1
            touched_cluster_ids.add(best_cluster.id)
            new_articles_by_cluster.setdefault(best_cluster.id, []).append(_new_article_delta(article))
            continue

        fallback_cluster = _find_near_duplicate_cluster(article, clusters)
        if fallback_cluster:
            article.cluster_id = fallback_cluster.id
            fallback_cluster.source_count += 1
            fallback_cluster.update_frequency += 1
            fallback_cluster.updated_at = datetime.now(timezone.utc)
            fallback_cluster.last_activity_at = article.published_at or datetime.now(timezone.utc)
            db.add(
                ClusterEvent(
                    cluster_id=fallback_cluster.id,
                    event_type="article_attached",
                    details={"article_id": article.id, "reason": "near_duplicate_title"},
                )
            )
            attached += 1
            touched_cluster_ids.add(fallback_cluster.id)
            new_articles_by_cluster.setdefault(fallback_cluster.id, []).append(_new_article_delta(article))
            continue

        slug = slugify(article.title)[:240] or f"cluster-{article.id}"
        new_cluster = Cluster(
            slug=f"{slug}-{article.id}",
            title=article.title,
            representative_article_id=article.id,
            representative_url=article.canonical_url,
            source_urls=[article.canonical_url],
            source_count=1,
            cluster_state="emerging",
            last_activity_at=article.published_at or datetime.now(timezone.utc),
            semantic_centroid=article.embedding or [],
        )
        db.add(new_cluster)
        db.flush()
        article.cluster_id = new_cluster.id
        clusters.append(new_cluster)
        db.add(
            ClusterEvent(
                cluster_id=new_cluster.id,
                event_type="cluster_created",
                details={"article_id": article.id},
            )
        )
        attached += 1
        touched_cluster_ids.add(new_cluster.id)
        new_articles_by_cluster.setdefault(new_cluster.id, []).append(_new_article_delta(article))

    _refresh_cluster_sources(db)
    db.commit()
    return {
        "attached": attached,
        "touched_cluster_ids": sorted(touched_cluster_ids),
        "new_articles_by_cluster": new_articles_by_cluster,
    }


def _refresh_cluster_sources(db: Session) -> None:
    by_cluster = defaultdict(set)
    rows = db.execute(select(Article.cluster_id, Article.canonical_url).where(Article.cluster_id.is_not(None))).all()
    for cluster_id, url in rows:
        by_cluster[cluster_id].add(url)

    clusters = db.scalars(select(CLUSTER_MODEL)).all()
    for cluster in clusters:
        cluster.source_urls = sorted(by_cluster.get(cluster.id, set()))
        cluster.source_count = len(cluster.source_urls)


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a))
    mag_b = math.sqrt(sum(y * y for y in b))
    if mag_a == 0 or mag_b == 0:
        return 0.0
    return dot / (mag_a * mag_b)


def blend_vectors(base: list[float], new_vec: list[float], alpha: float = 0.35) -> list[float]:
    if not base:
        return new_vec
    if not new_vec or len(base) != len(new_vec):
        return base
    return [((1 - alpha) * b) + (alpha * n) for b, n in zip(base, new_vec)]


def _domain(url: str | None) -> str:
    if not url:
        return ""
    try:
        return urlparse(url).netloc.lower()
    except Exception:
        return ""


def _new_article_delta(article: Article) -> dict[str, str | None]:
    text = f"{article.title or ''} {(article.summary or '')[:240]}"
    facts = []
    if any(ch.isdigit() for ch in text):
        facts.append("contains_new_numbers")
    lowered = text.lower()
    for token in ["fema", "nasa", "cdc", "fbi", "department", "governor", "mayor", "united nations"]:
        if token in lowered:
            facts.append(f"agency:{token}")
    for token in ["phoenix", "arizona", "new york", "washington", "california", "texas"]:
        if token in lowered:
            facts.append(f"location:{token}")

    return {
        "title": article.title,
        "source": article.source_name,
        "url": article.canonical_url,
        "published_at": article.published_at.isoformat() if article.published_at else None,
        "facts": ", ".join(facts[:4]) if facts else None,
    }


def _has_same_outlet_family(db: Session, cluster_id: int, source_name: str | None) -> bool:
    if not source_name:
        return False
    if not hasattr(db, "scalar"):
        return False
    source = db.scalar(select(Source).where(Source.name == source_name).limit(1))
    family = (source.outlet_family if source else None) or _family_from_name(source_name)
    if not family:
        return False

    rows = db.execute(
        select(Article.source_name)
        .where(Article.cluster_id == cluster_id)
        .limit(20)
    ).all()
    for (existing_name,) in rows:
        if _family_from_name(existing_name) == family:
            return True
    return False


def _family_from_name(name: str | None) -> str:
    if not name:
        return ""
    lowered = name.lower()
    for token in ["reuters", "ap", "bbc", "npr", "cnn", "nbc", "msnbc", "wsj", "ft"]:
        if token in lowered:
            return token
    return lowered.split()[0]


def _find_near_duplicate_cluster(article: Article, clusters: list[Cluster]) -> Cluster | None:
    article_tokens = set(tokenize(article.title))
    for cluster in clusters:
        if article.canonical_url in (cluster.source_urls or []):
            continue
        updated_ref = cluster.updated_at or datetime.now(timezone.utc)
        if (datetime.now(timezone.utc) - updated_ref) > MAX_CLUSTER_AGE:
            continue
        title_tokens = set(tokenize(cluster.title))
        overlap = len(article_tokens & title_tokens)
        if overlap >= 3:
            return cluster
    return None
