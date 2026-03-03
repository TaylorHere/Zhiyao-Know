import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.scheduler import add_task_job, create_extract_job_for_task, remove_task_job
from core.worker import enqueue_job
from models.extract_result import ExtractResult
from models.task import Task
from schemas.extract import ExtractOptions
from schemas.task import (
    ExtractResultOut,
    TaskCreate,
    TaskListResponse,
    TaskOut,
    TaskResultListResponse,
    TaskRunResponse,
    TaskStatusUpdate,
    TaskToggleRequest,
    TaskUpdate,
)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


def _task_name(task: Task) -> str:
    return task.name or task.site_name


def _task_url(task: Task) -> str:
    return task.url or task.target_url


def _task_schema_json(task: Task) -> str | None:
    return task.schema_json or task.json_schema


def _task_schema(task: Task):
    schema_json = _task_schema_json(task)
    if not schema_json:
        return None
    try:
        return json.loads(schema_json)
    except json.JSONDecodeError:
        return schema_json


def _task_mode(task: Task) -> str:
    return task.mode or "scrape"


def _task_status(task: Task) -> str:
    if task.status_text:
        return task.status_text
    return "active" if task.status else "paused"


def _task_options(task: Task) -> ExtractOptions | None:
    if not task.options_json:
        return None
    return ExtractOptions.model_validate(json.loads(task.options_json))


def _to_task_out(task: Task) -> TaskOut:
    return TaskOut(
        id=task.id,
        name=_task_name(task),
        url=_task_url(task),
        frequency=task.frequency,
        mode=_task_mode(task),
        status=_task_status(task),
        detail_url_pattern=task.detail_url_pattern,
        max_depth=task.max_depth or 1,
        concurrency=task.concurrency or 1,
        use_proxy=bool(task.use_proxy),
        schema=_task_schema(task),
        options=_task_options(task),
        last_run_time=task.last_run_time,
        last_items_count=task.last_items_count or 0,
        last_scrape_time=task.last_scrape_time,
    )


def _normalize_schema_json(payload: TaskCreate | TaskUpdate) -> str | None:
    if payload.json_schema:
        return payload.json_schema
    if payload.schema is not None:
        return json.dumps(payload.schema, ensure_ascii=False)
    return None


def _normalize_name(payload: TaskCreate | TaskUpdate) -> str | None:
    return payload.name or payload.site_name


def _normalize_url(payload: TaskCreate | TaskUpdate) -> str | None:
    if payload.url:
        return str(payload.url)
    if payload.target_url:
        return str(payload.target_url)
    return None


def _status_to_bool(status: str) -> bool:
    return status == "active"


@router.get("", response_model=TaskListResponse)
async def list_tasks(
    q: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=10, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    query = select(Task)
    count_query = select(func.count()).select_from(Task)

    if q:
        like_q = f"%{q}%"
        condition = (Task.name.ilike(like_q)) | (Task.site_name.ilike(like_q)) | (Task.url.ilike(like_q)) | (
            Task.target_url.ilike(like_q)
        )
        query = query.where(condition)
        count_query = count_query.where(condition)

    if status in {"active", "paused"}:
        target = status == "active"
        query = query.where((Task.status_text == status) | ((Task.status_text.is_(None)) & (Task.status.is_(target))))
        count_query = count_query.where(
            (Task.status_text == status) | ((Task.status_text.is_(None)) & (Task.status.is_(target)))
        )

    total = await session.scalar(count_query)
    result = await session.execute(
        query.order_by(Task.id.desc()).offset((page - 1) * size).limit(size)
    )
    items = [_to_task_out(item) for item in result.scalars().all()]
    return TaskListResponse(items=items, total=total or 0, page=page, size=size)


@router.post("", response_model=TaskOut)
async def create_task(payload: TaskCreate, session: AsyncSession = Depends(get_session)):
    task_name = _normalize_name(payload)
    task_url = _normalize_url(payload)
    schema_json = _normalize_schema_json(payload)
    if not task_name:
        raise HTTPException(status_code=400, detail="name is required")
    if not task_url:
        raise HTTPException(status_code=400, detail="url is required")
    if not schema_json:
        raise HTTPException(status_code=400, detail="schema/json_schema is required")

    options_json = json.dumps(payload.options.model_dump(), ensure_ascii=False)
    task = Task(
        name=task_name,
        site_name=task_name,
        url=task_url,
        target_url=task_url,
        frequency=payload.frequency,
        mode=payload.mode,
        detail_url_pattern=payload.detail_url_pattern,
        schema_json=schema_json,
        json_schema=schema_json,
        max_depth=payload.max_depth,
        concurrency=payload.concurrency,
        use_proxy=payload.use_proxy,
        options_json=options_json,
        status_text=payload.status,
        status=_status_to_bool(payload.status),
        last_items_count=0,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    if task.status:
        add_task_job(task)
    return _to_task_out(task)


@router.put("/{task_id}", response_model=TaskOut)
async def update_task(task_id: int, payload: TaskUpdate, session: AsyncSession = Depends(get_session)):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task_name = _normalize_name(payload)
    if task_name is not None:
        task.name = task_name
        task.site_name = task_name

    task_url = _normalize_url(payload)
    if task_url is not None:
        task.url = task_url
        task.target_url = task_url

    if payload.frequency is not None:
        task.frequency = payload.frequency
    if payload.mode is not None:
        task.mode = payload.mode
    if payload.detail_url_pattern is not None:
        task.detail_url_pattern = payload.detail_url_pattern

    schema_json = _normalize_schema_json(payload)
    if schema_json is not None:
        task.schema_json = schema_json
        task.json_schema = schema_json

    if payload.max_depth is not None:
        task.max_depth = payload.max_depth
    if payload.concurrency is not None:
        task.concurrency = payload.concurrency
    if payload.use_proxy is not None:
        task.use_proxy = payload.use_proxy
    if payload.options is not None:
        task.options_json = json.dumps(payload.options.model_dump(), ensure_ascii=False)

    if payload.status is not None:
        task.status_text = payload.status
        task.status = _status_to_bool(payload.status)

    await session.commit()
    await session.refresh(task)

    if task.status:
        add_task_job(task)
    else:
        remove_task_job(task.id)
    return _to_task_out(task)


@router.post("/{task_id}/run", response_model=TaskRunResponse)
async def run_task(task_id: int, session: AsyncSession = Depends(get_session)):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    if not _task_schema_json(task):
        raise HTTPException(status_code=400, detail="schema/json_schema is required")

    job = await create_extract_job_for_task(session, task, trigger_source="manual")
    await enqueue_job(job.id)
    return TaskRunResponse(job_id=job.id, status=job.status)


@router.post("/{task_id}/toggle", response_model=TaskOut)
async def toggle_task(
    task_id: int, payload: TaskToggleRequest, session: AsyncSession = Depends(get_session)
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    task.status = payload.active
    task.status_text = "active" if payload.active else "paused"
    await session.commit()
    await session.refresh(task)

    if payload.active:
        add_task_job(task)
    else:
        remove_task_job(task.id)
    return _to_task_out(task)


@router.put("/{task_id}/status", response_model=TaskOut)
async def update_task_status(
    task_id: int, payload: TaskStatusUpdate, session: AsyncSession = Depends(get_session)
):
    return await toggle_task(
        task_id=task_id, payload=TaskToggleRequest(active=payload.status), session=session
    )


@router.delete("/{task_id}")
async def delete_task(task_id: int, session: AsyncSession = Depends(get_session)):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    await session.delete(task)
    await session.commit()
    remove_task_job(task_id)
    return {"status": "deleted", "id": task_id}


@router.get("/{task_id}/results", response_model=TaskResultListResponse)
async def list_task_results(
    task_id: int,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
):
    task = await session.get(Task, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    total = await session.scalar(
        select(func.count()).select_from(ExtractResult).where(ExtractResult.task_id == task_id)
    )
    result = await session.execute(
        select(ExtractResult)
        .where(ExtractResult.task_id == task_id)
        .order_by(ExtractResult.id.desc())
        .offset((page - 1) * size)
        .limit(size)
    )

    items = []
    for row in result.scalars().all():
        try:
            data = json.loads(row.data_json)
        except json.JSONDecodeError:
            data = row.data_json
        items.append(
            ExtractResultOut(
                id=row.id,
                task_id=row.task_id,
                job_id=row.job_id,
                source_url=row.source_url,
                title=row.title,
                publish_date=row.publish_date,
                data=data,
                created_at=row.created_at,
            )
        )

    return TaskResultListResponse(items=items, total=total or 0, page=page, size=size)
