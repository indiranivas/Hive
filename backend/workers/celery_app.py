"""Celery app + beat schedule for scheduled ingestion."""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from api.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "hive",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["workers.ingest_git", "workers.deliver_notifications"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_max_tasks_per_child=200,
    task_time_limit=1800,
    task_soft_time_limit=1500,
    beat_schedule={
        "ingest-git": {
            "task": "workers.ingest_git.ingest_git",
            "schedule": crontab(minute=f"*/{max(1, settings.ingest_interval_minutes)}"),
        },
        "deliver-notifications": {
            "task": "workers.deliver_notifications.deliver",
            "schedule": crontab(minute="*/2"),
        },
    },
)
