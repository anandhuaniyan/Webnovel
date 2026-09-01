from celery import Celery

from app.core.config import get_settings

settings = get_settings()
celery_app = Celery("webnovel", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    result_expires=86_400,
    beat_schedule={
        "rights-recheck-daily": {
            "task": "webnovel.rights_recheck",
            "schedule": 86_400.0,
        },
        "retry-imports-every-five-minutes": {
            "task": "webnovel.retry_due_imports",
            "schedule": 300.0,
        },
        "storage-metrics-hourly": {
            "task": "webnovel.storage_metrics",
            "schedule": 3_600.0,
        },
        "temporary-cleanup-daily": {
            "task": "webnovel.cleanup_temporary_files",
            "schedule": 86_400.0,
        },
        "chapter-artwork-check-daily": {
            "task": "webnovel.check_chapter_artwork",
            "schedule": 86_400.0,
        },
    },
)
celery_app.autodiscover_tasks(["app.workers"])
