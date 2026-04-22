import logging
from datetime import datetime, timezone
from uuid import uuid4

from app.db.session import SessionLocal
from app.models import PipelineRun, PipelineStageEvent
from app.services.clustering import assign_articles_to_clusters
from app.services.ingestion import ingest_from_miniflux
from app.services.meili import MeiliService
from app.services.ranking import rank_clusters
from app.services.service_state import get_or_create_service_state
from app.services.social_context import ingest_social_context
from app.services.summarizer import summarize_clusters

logger = logging.getLogger(__name__)


def _record_stage(
    db,
    run_id: int,
    stage: str,
    started_at: datetime,
    status: str,
    *,
    details: dict | None = None,
    error: str | None = None,
) -> None:
    finished_at = datetime.now(timezone.utc)
    duration_ms = int(max(0.0, (finished_at - started_at).total_seconds() * 1000))
    db.add(
        PipelineStageEvent(
            run_id=run_id,
            stage=stage,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            duration_ms=duration_ms,
            details=details or {},
            error=error,
        )
    )
    db.commit()


def run_pipeline() -> dict:
    meili = MeiliService()

    with SessionLocal() as db:
        state = get_or_create_service_state(db)
        run = PipelineRun(run_token=uuid4().hex, status="running", started_at=datetime.now(timezone.utc))
        db.add(run)
        db.commit()
        db.refresh(run)

        state.last_pipeline_started_at = run.started_at
        state.last_pipeline_success = None
        state.last_pipeline_stage = "starting"
        state.last_pipeline_error = None
        db.commit()

        try:
            stage_errors: list[str] = []
            state.last_pipeline_stage = "ingest"
            db.commit()
            ingest_started = datetime.now(timezone.utc)
            try:
                ingest_result = ingest_from_miniflux(db)
                _record_stage(
                    db,
                    run.id,
                    "ingest",
                    ingest_started,
                    "success",
                    details={"inserted": ingest_result["inserted"], "processed_entries": len(ingest_result["processed_entry_ids"])},
                )
            except Exception as exc:
                _record_stage(db, run.id, "ingest", ingest_started, "failed", error=str(exc))
                raise

            state.last_ingest_run_at = datetime.now(timezone.utc)
            state.last_pipeline_stage = "cluster"
            db.commit()
            cluster_started = datetime.now(timezone.utc)
            try:
                cluster_result = assign_articles_to_clusters(db)
                _record_stage(
                    db,
                    run.id,
                    "cluster",
                    cluster_started,
                    "success",
                    details={
                        "attached": cluster_result["attached"],
                        "clusters_touched": len(cluster_result["touched_cluster_ids"]),
                    },
                )
            except Exception as exc:
                _record_stage(db, run.id, "cluster", cluster_started, "failed", error=str(exc))
                raise

            state.last_clustering_run_at = datetime.now(timezone.utc)
            state.last_pipeline_stage = "summarize"
            db.commit()
            summarized_cluster_ids: list[int] = []
            summarize_started = datetime.now(timezone.utc)
            try:
                summarized_cluster_ids = summarize_clusters(
                    db,
                    cluster_ids=cluster_result["touched_cluster_ids"],
                    changes_by_cluster=cluster_result["new_articles_by_cluster"],
                )
                _record_stage(
                    db,
                    run.id,
                    "summarize",
                    summarize_started,
                    "success",
                    details={"summarized": len(summarized_cluster_ids)},
                )
                state.last_summarization_run_at = datetime.now(timezone.utc)
                db.commit()
            except Exception as exc:
                state.last_summarization_run_at = datetime.now(timezone.utc)
                db.commit()
                msg = f"summarize_failed:{exc}"
                stage_errors.append(msg)
                _record_stage(db, run.id, "summarize", summarize_started, "failed", error=str(exc))
                logger.exception("Summarization stage failed: %s", exc)

            state.last_pipeline_stage = "rank"
            db.commit()
            rank_started = datetime.now(timezone.utc)
            try:
                rank_clusters(db, cluster_ids=cluster_result["touched_cluster_ids"])
                _record_stage(db, run.id, "rank", rank_started, "success")
                state.last_ranking_run_at = datetime.now(timezone.utc)
                db.commit()
            except Exception as exc:
                state.last_ranking_run_at = datetime.now(timezone.utc)
                db.commit()
                msg = f"rank_failed:{exc}"
                stage_errors.append(msg)
                _record_stage(db, run.id, "rank", rank_started, "failed", error=str(exc))
                logger.exception("Ranking stage failed: %s", exc)

            clusters_to_index = sorted(set(cluster_result["touched_cluster_ids"] + summarized_cluster_ids))
            state.last_pipeline_stage = "social"
            db.commit()
            social = {"clusters": 0, "items": 0}
            social_started = datetime.now(timezone.utc)
            if hasattr(db, "scalar"):
                try:
                    social = ingest_social_context(db, cluster_ids=clusters_to_index)
                    _record_stage(db, run.id, "social", social_started, "success", details=social)
                except Exception as exc:
                    msg = f"social_failed:{exc}"
                    stage_errors.append(msg)
                    _record_stage(db, run.id, "social", social_started, "failed", error=str(exc))
                    logger.exception("Social context stage failed: %s", exc)
            else:
                _record_stage(db, run.id, "social", social_started, "skipped", details={"reason": "db_capability_missing"})

            state.last_pipeline_stage = "index"
            db.commit()
            indexed = {"articles": 0, "clusters": 0}
            index_started = datetime.now(timezone.utc)
            try:
                indexed = meili.index_from_db(
                    db,
                    article_ids=ingest_result["inserted_article_ids"],
                    cluster_ids=clusters_to_index,
                )
                _record_stage(db, run.id, "index", index_started, "success", details=indexed)
            except Exception as exc:
                msg = f"index_failed:{exc}"
                stage_errors.append(msg)
                _record_stage(db, run.id, "index", index_started, "failed", error=str(exc))
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
                "run_token": run.run_token,
            }
            run.ingested_count = payload["ingested"]
            run.clustered_count = payload["clustered"]
            run.summarized_count = payload["summarized"]
            run.indexed_clusters_count = payload["indexed_clusters"]
            run.indexed_articles_count = payload["indexed_articles"]
            run.stage_error_count = len(stage_errors)
            run.error_summary = "; ".join(stage_errors) if stage_errors else None
            run.status = "warn" if stage_errors else "success"
            run.finished_at = datetime.now(timezone.utc)

            state.last_pipeline_success = True
            state.last_pipeline_stage = "complete_warn" if stage_errors else "complete"
            state.last_pipeline_error = run.error_summary
            state.last_pipeline_finished_at = run.finished_at
            db.commit()
            logger.info("Pipeline run complete: %s", payload)
            return payload
        except Exception as exc:
            run.status = "failed"
            run.error_summary = str(exc)
            run.stage_error_count = max(1, (run.stage_error_count or 0))
            run.finished_at = datetime.now(timezone.utc)

            state.last_pipeline_success = False
            state.last_pipeline_error = str(exc)
            state.last_pipeline_finished_at = run.finished_at
            db.commit()
            logger.exception("Pipeline failed: %s", exc)
            raise
