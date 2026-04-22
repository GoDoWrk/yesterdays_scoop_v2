from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "yesterdays_scoop",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.jobs"],
)

celery_app.conf.update(
    timezone="UTC",
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    beat_schedule={
        "scheduler-heartbeat": {
            "task": "app.tasks.jobs.scheduler_heartbeat_task",
            "schedule": 60,
        },
        "run-news-pipeline": {
            "task": "app.tasks.jobs.run_pipeline_task",
            "schedule": settings.poll_interval_minutes * 60,
        },
        "retry-miniflux-bootstrap": {
            "task": "app.tasks.jobs.retry_miniflux_bootstrap_task",
            "schedule": 60,
        },
        "ensure-meili-indexes": {
            "task": "app.tasks.jobs.ensure_meili_indexes_task",
            "schedule": 300,
        },
    },
)
