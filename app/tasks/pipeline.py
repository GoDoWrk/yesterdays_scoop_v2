import logging
from datetime import datetime, timezone

from app.db.session import SessionLocal
from app.services.clustering import assign_articles_to_clusters
from app.services.ingestion import ingest_from_miniflux
from app.services.meili import MeiliService
from app.services.ranking import rank_clusters
from app.services.service_state import get_or_create_service_state
from app.services.social_context import ingest_social_context
from app.services.summarizer import summarize_clusters

logger = logging.getLogger(__name__)


def run_pipeline() -> dict:
    meili = MeiliService()

    with SessionLocal() as db:
        state = get_or_create_service_state(db)
        state.last_pipeline_started_at = datetime.now(timezone.utc)
        state.last_pipeline_success = None
        state.last_pipeline_stage = "starting"
        state.last_pipeline_error = None
        db.commit()

        try:
            stage_errors: list[str] = []
            state.last_pipeline_stage = "ingest"
            db.commit()
            ingest_result = ingest_from_miniflux(db)
            state.last_pipeline_stage = "cluster"
            db.commit()
            cluster_result = assign_articles_to_clusters(db)
            state.last_pipeline_stage = "summarize"
            db.commit()
            summarized_cluster_ids: list[int] = []
            try:
                summarized_cluster_ids = summarize_clusters(
                    db,
                    cluster_ids=cluster_result["touched_cluster_ids"],
                    changes_by_cluster=cluster_result["new_articles_by_cluster"],
                )
            except Exception as exc:
                msg = f"summarize_failed:{exc}"
                stage_errors.append(msg)
                logger.exception("Summarization stage failed: %s", exc)
            state.last_pipeline_stage = "rank"
            db.commit()
            try:
                rank_clusters(db, cluster_ids=cluster_result["touched_cluster_ids"])
            except Exception as exc:
                msg = f"rank_failed:{exc}"
                stage_errors.append(msg)
                logger.exception("Ranking stage failed: %s", exc)

            clusters_to_index = sorted(set(cluster_result["touched_cluster_ids"] + summarized_cluster_ids))
            state.last_pipeline_stage = "social"
            db.commit()
            social = {"clusters": 0, "items": 0}
            if hasattr(db, "scalar"):
                try:
                    social = ingest_social_context(db, cluster_ids=clusters_to_index)
                except Exception as exc:
                    msg = f"social_failed:{exc}"
                    stage_errors.append(msg)
                    logger.exception("Social context stage failed: %s", exc)

            state.last_pipeline_stage = "index"
            db.commit()
            indexed = {"articles": 0, "clusters": 0}
            try:
                indexed = meili.index_from_db(
                    db,
                    article_ids=ingest_result["inserted_article_ids"],
                    cluster_ids=clusters_to_index,
                )
            except Exception as exc:
                msg = f"index_failed:{exc}"
                stage_errors.append(msg)
                logger.exception("Indexing stage failed: %s", exc)

            payload = {
                "ingested": ingest_result["inserted"],
                "processed_entries": len(ingest_result["processed_entry_ids"]),
                "clustered": cluster_result["attached"],
                "clusters_touched": len(cluster_result["touched_cluster_ids"]),
                "summarized": len(summarized_cluster_ids),
                "indexed_articles": indexed["articles"],
                "indexed_clusters": indexed["clusters"],
                "social_clusters": social["clusters"],
                "social_items": social["items"],
                "stage_errors": stage_errors,
            }
            state.last_pipeline_success = True
            state.last_pipeline_stage = "complete_warn" if stage_errors else "complete"
            state.last_pipeline_error = "; ".join(stage_errors) if stage_errors else None
            state.last_pipeline_finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("Pipeline run complete: %s", payload)
            return payload
        except Exception as exc:
            state.last_pipeline_success = False
            state.last_pipeline_error = str(exc)
            state.last_pipeline_finished_at = datetime.now(timezone.utc)
            db.commit()
            logger.exception("Pipeline failed: %s", exc)
            raise
