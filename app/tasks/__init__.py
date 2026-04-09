"""Celery application configuration."""
from celery import Celery
from celery.schedules import crontab
from app.config import settings

celery_app = Celery("fr_arb", broker=settings.redis_url, backend=settings.redis_url)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Tokyo",
    enable_utc=True,
    task_track_started=True,
)

celery_app.conf.beat_schedule = {
    # Global FR scan: 30 min before settlement (0:28, 8:28, 16:28 JST)
    "global-fr-scan": {
        "task": "app.tasks.scan_task.global_fr_scan",
        "schedule": crontab(minute=28, hour="0,8,16"),
    },
    # Per-user auto-entry: 2 min after scan
    "auto-entry-check": {
        "task": "app.tasks.auto_trade_task.check_all_users_entry",
        "schedule": crontab(minute=30, hour="0,8,16"),
    },
    # Per-user auto-close: every 5 min
    "auto-close-check": {
        "task": "app.tasks.auto_trade_task.check_all_users_close",
        "schedule": crontab(minute="*/5"),
    },
}

celery_app.autodiscover_tasks(["app.tasks"])
