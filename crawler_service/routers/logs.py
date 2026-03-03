import csv
import io
from datetime import date, datetime, time

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from models.log import Log
from models.task import Task
from schemas.log import LogListResponse, LogOut

router = APIRouter(prefix="/api/v1/logs", tags=["logs"])


def _apply_filters(query, count_query, status, start_date, end_date, job_id):
    if status:
        query = query.where(Log.status == status)
        count_query = count_query.where(Log.status == status)

    if start_date:
        start_dt = datetime.combine(start_date, time.min)
        query = query.where(Log.execution_time >= start_dt)
        count_query = count_query.where(Log.execution_time >= start_dt)

    if end_date:
        end_dt = datetime.combine(end_date, time.max)
        query = query.where(Log.execution_time <= end_dt)
        count_query = count_query.where(Log.execution_time <= end_dt)

    if job_id:
        query = query.where(Log.job_id == job_id)
        count_query = count_query.where(Log.job_id == job_id)

    return query, count_query


@router.get("", response_model=LogListResponse)
async def list_logs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=100),
    status: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    job_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    query = (
        select(Log, Task.name, Task.site_name)
        .outerjoin(Task, Task.id == Log.task_id)
        .order_by(Log.execution_time.desc())
    )
    count_query = select(func.count()).select_from(Log)
    query, count_query = _apply_filters(query, count_query, status, start_date, end_date, job_id)

    total = await session.scalar(count_query)
    result = await session.execute(query.offset((page - 1) * size).limit(size))

    items = []
    for log, task_name, site_name in result.all():
        items.append(
            LogOut(
                id=log.id,
                task_id=log.task_id,
                task_name=task_name or site_name,
                job_id=log.job_id,
                execution_time=log.execution_time,
                status=log.status,
                error_message=log.error_message,
                detail_log=log.detail_log,
                items_count=log.items_count,
                token_usage=log.token_usage,
            )
        )

    return LogListResponse(items=items, total=total or 0, page=page, size=size)


@router.get("/export")
async def export_logs(
    status: str | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    job_id: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    query = (
        select(Log, Task.name, Task.site_name)
        .outerjoin(Task, Task.id == Log.task_id)
        .order_by(Log.execution_time.desc())
    )
    count_query = select(func.count()).select_from(Log)
    query, _ = _apply_filters(query, count_query, status, start_date, end_date, job_id)

    result = await session.execute(query)

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "execution_time",
            "task_id",
            "task_name",
            "job_id",
            "status",
            "items_count",
            "token_usage",
            "error_message",
            "detail_log",
        ]
    )

    for log, task_name, site_name in result.all():
        writer.writerow(
            [
                log.id,
                log.execution_time.isoformat(),
                log.task_id,
                task_name or site_name or "",
                log.job_id or "",
                log.status,
                log.items_count,
                log.token_usage,
                log.error_message or "",
                log.detail_log or "",
            ]
        )

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=logs.csv"},
    )
