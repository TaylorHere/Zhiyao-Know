from celery import Celery

from core.config import settings

celery_app = Celery(
    "crawler_service",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    enable_utc=False,
    task_track_started=True,
    imports=("core.celery_tasks",),
)
