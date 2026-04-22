from app.db.session import SessionLocal
from app.services.bootstrap import attempt_miniflux_bootstrap, ensure_app_settings
from app.services.meili import MeiliService
from app.services.service_state import mark_scheduler_tick, mark_worker_heartbeat
from app.tasks.celery_app import celery_app
from app.tasks.pipeline import run_pipeline


@celery_app.task(name="app.tasks.jobs.run_pipeline_task", autoretry_for=(Exception,), retry_backoff=True, max_retries=3)
def run_pipeline_task() -> dict:
    with SessionLocal() as db:
        mark_scheduler_tick(db)
        mark_worker_heartbeat(db)
    return run_pipeline()


@celery_app.task(name="app.tasks.jobs.retry_miniflux_bootstrap_task")
def retry_miniflux_bootstrap_task() -> dict:
    with SessionLocal() as db:
        mark_scheduler_tick(db)
        mark_worker_heartbeat(db)
        settings = ensure_app_settings(db)
        if settings.miniflux_bootstrap_completed:
            return {"skipped": True, "reason": "already_bootstrapped"}
        ok = attempt_miniflux_bootstrap(db, app_settings=settings, reason="scheduled_retry")
        return {
            "skipped": False,
            "ok": ok,
            "retry_count": settings.miniflux_retry_count,
            "error": settings.miniflux_bootstrap_error,
        }


@celery_app.task(name="app.tasks.jobs.scheduler_heartbeat_task")
def scheduler_heartbeat_task() -> dict:
    with SessionLocal() as db:
        mark_scheduler_tick(db)
        mark_worker_heartbeat(db)
    return {"ok": True}


@celery_app.task(name="app.tasks.jobs.ensure_meili_indexes_task")
def ensure_meili_indexes_task() -> dict:
    with SessionLocal() as db:
        mark_scheduler_tick(db)
        mark_worker_heartbeat(db)
    try:
        MeiliService().bootstrap_indexes()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
