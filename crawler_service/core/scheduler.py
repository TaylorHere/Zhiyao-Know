import asyncio
import json
from datetime import datetime
from uuid import uuid4

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import SessionLocal
from core.worker import enqueue_job
from models.extract_job import ExtractJob
from models.log import Log
from models.task import Task

scheduler = BackgroundScheduler(timezone="Asia/Shanghai")


def _job_id(task_id: int) -> str:
    return f"task-{task_id}"


def _task_name(task: Task) -> str:
    return task.name or task.site_name


def _task_url(task: Task) -> str:
    return task.url or task.target_url


def _task_schema_json(task: Task) -> str | None:
    return task.schema_json or task.json_schema


def _task_mode(task: Task) -> str:
    return task.mode or "scrape"


def _task_active(task: Task) -> bool:
    if task.status_text:
        return task.status_text == "active"
    return bool(task.status)


async def create_extract_job_for_task(
    session: AsyncSession, task: Task, trigger_source: str = "manual"
) -> ExtractJob:
    payload = {
        "task_id": task.id,
        "name": _task_name(task),
        "url": _task_url(task),
        "mode": _task_mode(task),
        "trigger_source": trigger_source,
        "schema_json": _task_schema_json(task),
        "max_depth": task.max_depth or 1,
        "concurrency": task.concurrency or 1,
        "use_proxy": bool(task.use_proxy),
        "detail_url_pattern": task.detail_url_pattern,
    }
    if task.options_json:
        payload["options"] = json.loads(task.options_json)

    now = datetime.utcnow()
    job = ExtractJob(
        id=uuid4().hex,
        task_id=task.id,
        status="pending",
        request_json=json.dumps(payload, ensure_ascii=False),
        created_at=now,
        updated_at=now,
    )
    session.add(job)
    await session.commit()
    return job


async def _execute_task(task_id: int):
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task or not _task_active(task):
            return

        if not _task_schema_json(task):
            log = Log(
                task_id=task.id,
                execution_time=datetime.utcnow(),
                status="failed",
                error_message="json_schema is required",
                items_count=0,
                token_usage=0,
            )
            session.add(log)
            await session.commit()
            return

        job = await create_extract_job_for_task(session, task, trigger_source="schedule")
        await enqueue_job(job.id)


def _run_task(task_id: int):
    asyncio.run(_execute_task(task_id))


def _build_trigger(frequency: str):
    normalized = (frequency or "").strip().lower()
    if normalized == "hourly":
        return IntervalTrigger(hours=1)
    if normalized == "daily":
        return IntervalTrigger(days=1)
    if normalized == "weekly":
        return IntervalTrigger(weeks=1)
    if normalized == "manual":
        return None
    try:
        return CronTrigger.from_crontab(frequency)
    except ValueError:
        return IntervalTrigger(days=1)


def add_task_job(task: Task):
    trigger = _build_trigger(task.frequency)
    if trigger is None:
        remove_task_job(task.id)
        return
    scheduler.add_job(
        _run_task,
        trigger,
        id=_job_id(task.id),
        args=[task.id],
        replace_existing=True,
    )


def remove_task_job(task_id: int):
    job_id = _job_id(task_id)
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


async def start_scheduler():
    async with SessionLocal() as session:
        result = await session.execute(select(Task))
        tasks = result.scalars().all()

    scheduler.remove_all_jobs()
    for task in tasks:
        if _task_active(task):
            add_task_job(task)

    if not scheduler.running:
        scheduler.start()


def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
