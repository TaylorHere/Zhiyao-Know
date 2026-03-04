import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from models.extract_job import ExtractJob
from models.extract_result import ExtractResult
from models.job_page import JobPage
from models.task import Task
from schemas.job import JobListResponse, JobOut, JobPageListResponse, JobPageOut

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


def _trigger_source_from_request(request_json: str | None) -> str:
    if not request_json:
        return "unknown"
    try:
        payload = json.loads(request_json)
    except json.JSONDecodeError:
        return "unknown"
    return payload.get("trigger_source") or "unknown"


def _extract_content_markdown(data: object) -> str | None:
    if isinstance(data, dict):
        content = data.get("content")
        if isinstance(content, str):
            return content
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and isinstance(item.get("content"), str):
                return item["content"]
    return None


@router.get("", response_model=JobListResponse)
async def list_jobs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    task_id: int | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    query = (
        select(ExtractJob, Task.name, Task.site_name)
        .outerjoin(Task, Task.id == ExtractJob.task_id)
        .order_by(ExtractJob.created_at.desc())
    )
    count_query = select(func.count()).select_from(ExtractJob)

    if status:
        query = query.where(ExtractJob.status == status)
        count_query = count_query.where(ExtractJob.status == status)
    if task_id is not None:
        query = query.where(ExtractJob.task_id == task_id)
        count_query = count_query.where(ExtractJob.task_id == task_id)

    total = await session.scalar(count_query)
    rows = (await session.execute(query.offset((page - 1) * size).limit(size))).all()
    job_ids = [job.id for job, _, _ in rows]

    page_stats: dict[str, dict[str, int]] = {}
    if job_ids:
        stats_rows = (
            await session.execute(
                select(JobPage.job_id, JobPage.status, func.count())
                .where(JobPage.job_id.in_(job_ids))
                .group_by(JobPage.job_id, JobPage.status)
            )
        ).all()
        for job_id, status_name, count in stats_rows:
            bucket = page_stats.setdefault(job_id, {"total": 0})
            key = status_name if isinstance(status_name, str) else "pending"
            bucket[key] = int(count or 0)
            bucket["total"] += int(count or 0)

    items: list[JobOut] = []
    for job, task_name, site_name in rows:
        source = _trigger_source_from_request(job.request_json)
        stats = page_stats.get(job.id, {})
        items.append(
            JobOut(
                job_id=job.id,
                task_id=job.task_id,
                task_name=task_name or site_name,
                status=job.status,
                trigger_source=source,
                created_at=job.created_at,
                updated_at=job.updated_at,
                error_message=job.error_message,
                list_page_count=job.list_page_count or 0,
                discovered_links=job.discovered_links or 0,
                effective_links=job.effective_links or 0,
                total_pages=int(stats.get("total", 0)),
                pending_pages=int(stats.get("pending", 0)),
                running_pages=int(stats.get("running", 0)),
                success_pages=int(stats.get("success", 0)),
                failed_pages=int(stats.get("failed", 0)),
                skipped_pages=int(stats.get("skipped", 0)),
            )
        )

    return JobListResponse(items=items, total=total or 0, page=page, size=size)


@router.get("/{job_id}/pages", response_model=JobPageListResponse)
async def list_job_pages(
    job_id: str,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
):
    query = select(JobPage).where(JobPage.job_id == job_id)
    count_query = select(func.count()).select_from(JobPage).where(JobPage.job_id == job_id)
    if status:
        query = query.where(JobPage.status == status)
        count_query = count_query.where(JobPage.status == status)
    query = query.order_by(JobPage.id.desc())

    total = await session.scalar(count_query)
    page_rows = (
        await session.execute(query.offset((page - 1) * size).limit(size))
    ).scalars().all()

    urls = list({row.page_url for row in page_rows if row.page_url})
    result_by_task: dict[tuple[str, int | None], ExtractResult] = {}
    latest_result_by_url: dict[str, ExtractResult] = {}
    if urls:
        result_rows = (
            await session.execute(
                select(ExtractResult)
                .where(ExtractResult.source_url.in_(urls))
                .order_by(ExtractResult.created_at.desc(), ExtractResult.id.desc())
            )
        ).scalars().all()
        for item in result_rows:
            key = (item.source_url, item.task_id)
            if key not in result_by_task:
                result_by_task[key] = item
            if item.source_url not in latest_result_by_url:
                latest_result_by_url[item.source_url] = item

    items: list[JobPageOut] = []
    for row in page_rows:
        extract_row = result_by_task.get((row.page_url, row.task_id)) or latest_result_by_url.get(row.page_url)
        content_markdown = None
        title = None
        publish_date = None
        if extract_row:
            title = extract_row.title
            publish_date = extract_row.publish_date
            try:
                data = json.loads(extract_row.data_json)
            except json.JSONDecodeError:
                data = {}
            content_markdown = _extract_content_markdown(data)
        items.append(
            JobPageOut(
                id=row.id,
                job_id=row.job_id,
                task_id=row.task_id,
                page_url=row.page_url,
                status=row.status,
                message=row.message,
                started_at=row.started_at,
                finished_at=row.finished_at,
                token_usage=row.token_usage,
                content_markdown=content_markdown,
                title=title,
                publish_date=publish_date,
            )
        )

    return JobPageListResponse(items=items, total=total or 0, page=page, size=size)
