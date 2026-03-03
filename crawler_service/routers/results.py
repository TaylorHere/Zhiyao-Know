import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from models.extract_result import ExtractResult
from models.task import Task
from schemas.result import ResultListResponse, ResultOut

router = APIRouter(prefix="/api/v1/results", tags=["results"])


@router.get("", response_model=ResultListResponse)
async def list_results(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    task_id: int | None = Query(default=None),
    q: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    query = (
        select(ExtractResult, Task.name, Task.site_name)
        .outerjoin(Task, Task.id == ExtractResult.task_id)
        .order_by(ExtractResult.id.desc())
    )
    count_query = select(func.count()).select_from(ExtractResult)

    if task_id is not None:
        query = query.where(ExtractResult.task_id == task_id)
        count_query = count_query.where(ExtractResult.task_id == task_id)
    if q:
        like_q = f"%{q}%"
        condition = (ExtractResult.source_url.ilike(like_q)) | (ExtractResult.title.ilike(like_q))
        query = query.where(condition)
        count_query = count_query.where(condition)

    total = await session.scalar(count_query)
    rows = (
        await session.execute(query.offset((page - 1) * size).limit(size))
    ).all()

    items: list[ResultOut] = []
    for row, task_name, site_name in rows:
        try:
            data = json.loads(row.data_json)
        except json.JSONDecodeError:
            data = row.data_json
        items.append(
            ResultOut(
                id=row.id,
                task_id=row.task_id,
                task_name=task_name or site_name,
                job_id=row.job_id,
                source_url=row.source_url,
                title=row.title,
                publish_date=row.publish_date,
                data=data,
                created_at=row.created_at,
            )
        )
    return ResultListResponse(items=items, total=total or 0, page=page, size=size)
