import asyncio
import json
import re
from datetime import datetime
from fnmatch import fnmatch
from urllib.parse import urlparse
from typing import Any

from sqlalchemy import select

from core.config import settings
from core.database import SessionLocal
from models.extract_job import ExtractJob
from models.extract_result import ExtractResult
from models.job_page import JobPage
from models.log import Log
from models.task import Task
from schemas.extract import ExtractOptions
from services.scraper_service import crawl_task_target, extract_with_llm

_queue: asyncio.Queue[str] | None = None
_workers: list[asyncio.Task] = []


async def enqueue_job(job_id: str):
    if settings.use_celery:
        from core.celery_tasks import process_extract_job

        process_extract_job.delay(job_id)
        return
    if _queue is None:
        return
    await _queue.put(job_id)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value:
        return None
    normalized = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _extract_title(data: Any) -> str | None:
    if not isinstance(data, dict):
        return None
    value = data.get("title") or data.get("name")
    return str(value) if value else None


def _extract_publish_date(data: Any) -> datetime | None:
    if not isinstance(data, dict):
        return None
    value = data.get("publish_date") or data.get("published_at") or data.get("date")
    return _parse_datetime(value)


def _match_url(url: str, pattern: str | None) -> bool:
    if not pattern:
        return True
    try:
        return bool(re.search(pattern, url))
    except re.error:
        return fnmatch(url, pattern)


def _count_list_pages(target_url: str, urls: list[str]) -> int:
    try:
        target = urlparse(target_url)
        target_path = target.path or "/"
        target_dir = target_path.rsplit("/", 1)[0]
    except Exception:
        return 1
    count = 1
    for url in urls:
        try:
            parsed = urlparse(url)
        except Exception:
            continue
        if parsed.netloc != target.netloc:
            continue
        path = parsed.path or ""
        if not path.startswith(target_dir):
            continue
        if re.search(r"(index(_\d+)?|list(_\d+)?)\.html?$", path, flags=re.IGNORECASE):
            count += 1
    return max(1, len(set([target_path])) + count - 1)


def _fallback_effective_urls(target_url: str, urls: list[str]) -> list[str]:
    try:
        target = urlparse(target_url)
    except Exception:
        return []
    output: list[str] = []
    for raw_url in urls:
        try:
            parsed = urlparse(raw_url)
        except Exception:
            continue
        if parsed.netloc != target.netloc:
            continue
        path = (parsed.path or "").lower()
        if not path.endswith(".htm") and not path.endswith(".html"):
            continue
        if raw_url == target_url:
            continue
        output.append(raw_url)
    return sorted(set(output))


def _normalize_scheme_by_target(target_url: str, urls: list[str]) -> list[str]:
    try:
        target = urlparse(target_url)
        target_scheme = target.scheme or "https"
        target_host = target.netloc
    except Exception:
        return urls
    output: list[str] = []
    for raw_url in urls:
        try:
            parsed = urlparse(raw_url)
        except Exception:
            output.append(raw_url)
            continue
        if parsed.netloc == target_host and parsed.scheme and parsed.scheme != target_scheme:
            normalized = f"{target_scheme}://{parsed.netloc}{parsed.path or ''}"
            if parsed.query:
                normalized += f"?{parsed.query}"
            if parsed.fragment:
                normalized += f"#{parsed.fragment}"
            output.append(normalized)
        else:
            output.append(raw_url)
    return output


async def _build_detail_log(job_id: str, mode: str, list_meta: dict[str, int | float | str] | None = None) -> str:
    async with SessionLocal() as session:
        page_rows = (
            await session.execute(
                select(JobPage).where(JobPage.job_id == job_id).order_by(JobPage.id.asc())
            )
        ).scalars().all()
    lines = [
        f"模式: {mode}",
        f"页面执行记录数: {len(page_rows)}",
    ]
    if list_meta:
        lines.append(f"列表页数: {list_meta.get('list_page_count', 0)}")
        lines.append(f"发现链接数: {list_meta.get('discovered_links', 0)}")
        lines.append(f"有效链接数: {list_meta.get('effective_links', 0)}")
        if int(list_meta.get("fallback_used", 0) or 0) > 0:
            lines.append("详情链接过滤未命中，已启用自动兜底规则")
    for row in page_rows[:200]:
        st = row.status
        start = row.started_at.isoformat() if row.started_at else "-"
        end = row.finished_at.isoformat() if row.finished_at else "-"
        msg = row.message or ""
        lines.append(f"[{st}] {row.page_url} | start={start} | end={end} | token={row.token_usage} | {msg}")
    if len(page_rows) > 200:
        lines.append(f"... 其余 {len(page_rows) - 200} 条省略")
    return "\n".join(lines)


async def _upsert_extract_result(
    task_id: int | None,
    job_id: str,
    source_url: str,
    data: Any,
):
    async with SessionLocal() as session:
        existing = await session.scalar(
            select(ExtractResult).where(ExtractResult.source_url == source_url)
        )
        if existing:
            existing.task_id = task_id
            existing.job_id = job_id
            existing.title = _extract_title(data)
            existing.publish_date = _extract_publish_date(data)
            existing.data_json = json.dumps(data, ensure_ascii=False)
        else:
            session.add(
                ExtractResult(
                    task_id=task_id,
                    job_id=job_id,
                    source_url=source_url,
                    title=_extract_title(data),
                    publish_date=_extract_publish_date(data),
                    data_json=json.dumps(data, ensure_ascii=False),
                    created_at=datetime.utcnow(),
                )
            )
        await session.commit()


async def _create_job_page(
    job_id: str,
    task_id: int | None,
    page_url: str,
    status: str,
    message: str | None = None,
) -> int:
    now = datetime.utcnow()
    async with SessionLocal() as session:
        row = JobPage(
            job_id=job_id,
            task_id=task_id,
            page_url=page_url,
            status=status,
            message=message,
            started_at=now if status == "running" else None,
            finished_at=now if status in {"success", "failed", "skipped"} else None,
            token_usage=0,
            created_at=now,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def _finish_job_page(
    row_id: int,
    status: str,
    message: str | None = None,
    token_usage: int = 0,
):
    async with SessionLocal() as session:
        row = await session.get(JobPage, row_id)
        if not row:
            return
        row.status = status
        row.message = message
        row.finished_at = datetime.utcnow()
        row.token_usage = token_usage
        await session.commit()


async def _run_list_mode_job(job: ExtractJob, payload: dict[str, Any]):
    target_url = payload["url"]
    schema_json = payload.get("schema_json") or payload.get("json_schema")
    detail_url_pattern = payload.get("detail_url_pattern")
    task_id = payload.get("task_id")
    options = ExtractOptions.model_validate(payload.get("options") or {})
    concurrency = max(1, int(payload.get("concurrency") or 1))

    discovered = await crawl_task_target(target_url, options=options)
    filtered_urls = sorted({url for url in discovered if _match_url(url, detail_url_pattern)})
    fallback_used = 0
    if detail_url_pattern and len(filtered_urls) == 0 and len(discovered) > 0:
        filtered_urls = _fallback_effective_urls(target_url, discovered)
        fallback_used = 1
    filtered_urls = _normalize_scheme_by_target(target_url, filtered_urls)
    filtered_urls = sorted(set(filtered_urls))
    list_page_count = _count_list_pages(target_url, discovered)

    if filtered_urls:
        async with SessionLocal() as session:
            query = select(ExtractResult.source_url).where(ExtractResult.source_url.in_(filtered_urls))
            if task_id is not None:
                query = query.where(ExtractResult.task_id == task_id)
            result = await session.execute(query)
            existing_urls = {row[0] for row in result.all()}
    else:
        existing_urls = set()

    semaphore = asyncio.Semaphore(concurrency)
    all_data: list[Any] = []
    total_tokens = 0
    failed_count = 0

    async def _extract_one(url: str):
        nonlocal total_tokens, failed_count
        if url in existing_urls:
            await _create_job_page(
                job_id=job.id,
                task_id=task_id,
                page_url=url,
                status="skipped",
                message="已爬取，本次跳过",
            )
            return
        async with semaphore:
            page_row_id = await _create_job_page(
                job_id=job.id,
                task_id=task_id,
                page_url=url,
                status="running",
            )
            try:
                data, usage = await extract_with_llm(url=url, json_schema=schema_json, options=options)
                await _upsert_extract_result(task_id=task_id, job_id=job.id, source_url=url, data=data)
                all_data.append(data)
                total_tokens += usage.total_tokens
                await _finish_job_page(
                    row_id=page_row_id,
                    status="success",
                    token_usage=usage.total_tokens,
                )
            except Exception as exc:
                failed_count += 1
                await _finish_job_page(
                    row_id=page_row_id,
                    status="failed",
                    message=str(exc),
                )

    await asyncio.gather(*[_extract_one(url) for url in filtered_urls])
    if failed_count > 0:
        raise RuntimeError(f"部分页面抓取失败: {failed_count} 个页面失败")
    meta = {
        "list_page_count": list_page_count,
        "discovered_links": len(discovered),
        "effective_links": len(filtered_urls),
        "fallback_used": fallback_used,
    }
    return all_data, total_tokens, meta


async def _run_single_url_job(job: ExtractJob, payload: dict[str, Any]):
    options = ExtractOptions.model_validate(payload.get("options") or {})
    schema_json = payload.get("schema_json") or payload.get("json_schema")
    url = payload["url"]
    task_id = payload.get("task_id")

    async with SessionLocal() as session:
        query = select(ExtractResult.id).where(ExtractResult.source_url == url)
        if task_id is not None:
            query = query.where(ExtractResult.task_id == task_id)
        existing = await session.scalar(query)
    if existing:
        await _create_job_page(
            job_id=job.id,
            task_id=task_id,
            page_url=url,
            status="skipped",
            message="已爬取，本次跳过",
        )
        return [], 0, None

    page_row_id = await _create_job_page(job_id=job.id, task_id=task_id, page_url=url, status="running")
    try:
        data, usage = await extract_with_llm(url=url, json_schema=schema_json, options=options)
        await _upsert_extract_result(task_id=task_id, job_id=job.id, source_url=url, data=data)
        await _finish_job_page(row_id=page_row_id, status="success", token_usage=usage.total_tokens)
        return data, usage.total_tokens, None
    except Exception as exc:
        await _finish_job_page(row_id=page_row_id, status="failed", message=str(exc))
        raise


async def run_job_by_id(job_id: str):
    async with SessionLocal() as session:
        job = await session.get(ExtractJob, job_id)
        if not job:
            return

        job.status = "running"
        job.updated_at = datetime.utcnow()
        await session.commit()

        items_count = 0
        token_usage = 0
        mode = "scrape"
        list_meta: dict[str, int] | None = None
        try:
            payload = json.loads(job.request_json)
            mode = (payload.get("mode") or "scrape").lower()

            if mode == "list":
                data, token_usage, list_meta = await _run_list_mode_job(job, payload)
                items_count = len(data)
            elif mode == "auto":
                discovered = await crawl_task_target(payload["url"], options=ExtractOptions.model_validate(payload.get("options") or {}))
                if discovered:
                    payload["mode"] = "list"
                    data, token_usage, list_meta = await _run_list_mode_job(job, payload)
                    items_count = len(data)
                else:
                    data, token_usage, _ = await _run_single_url_job(job, payload)
                    if isinstance(data, list):
                        items_count = len(data)
                    elif isinstance(data, dict):
                        items_count = 1
            else:
                data, token_usage, _ = await _run_single_url_job(job, payload)
                if isinstance(data, list):
                    items_count = len(data)
                elif isinstance(data, dict):
                    items_count = 1

            usage = {
                "prompt_tokens": 0,
                "completion_tokens": token_usage,
                "total_tokens": token_usage,
                "model": settings.llm_model,
            }
            job.status = "success"
            job.result_json = json.dumps(data, ensure_ascii=False)
            job.usage_json = json.dumps(usage, ensure_ascii=False)
            job.error_message = None
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)

        now = datetime.utcnow()
        if list_meta:
            job.list_page_count = int(list_meta.get("list_page_count", 0))
            job.discovered_links = int(list_meta.get("discovered_links", 0))
            job.effective_links = int(list_meta.get("effective_links", 0))
        else:
            job.list_page_count = 0
            job.discovered_links = 0
            job.effective_links = 0
        job.updated_at = now
        await session.commit()

        if job.task_id is not None:
            task = await session.get(Task, job.task_id)
            if task:
                task.last_scrape_time = now
                task.last_run_time = now
                task.last_items_count = items_count
                await session.commit()

        detail_log = await _build_detail_log(job_id=job.id, mode=mode, list_meta=list_meta)
        log = Log(
            task_id=job.task_id,
            job_id=job.id,
            execution_time=now,
            status=job.status,
            error_message=job.error_message,
            detail_log=detail_log,
            items_count=items_count,
            token_usage=token_usage,
        )
        session.add(log)
        await session.commit()


async def _worker_loop():
    if _queue is None:
        return
    while True:
        job_id = await _queue.get()
        try:
            await run_job_by_id(job_id)
        finally:
            _queue.task_done()


async def _enqueue_pending_jobs():
    if settings.use_celery:
        return
    async with SessionLocal() as session:
        result = await session.execute(
            select(ExtractJob.id).where(ExtractJob.status.in_(["pending", "running"]))
        )
        ids = [row[0] for row in result.all()]

    for job_id in ids:
        await enqueue_job(job_id)


async def start_workers():
    if settings.use_celery:
        return
    if _queue is not None:
        return
    concurrency = settings.worker_concurrency
    queue: asyncio.Queue[str] = asyncio.Queue()
    globals()["_queue"] = queue
    await _enqueue_pending_jobs()
    for _ in range(concurrency):
        _workers.append(asyncio.create_task(_worker_loop()))


async def stop_workers():
    if settings.use_celery:
        return
    for worker in list(_workers):
        worker.cancel()
    if _workers:
        await asyncio.gather(*_workers, return_exceptions=True)
    _workers.clear()
    globals()["_queue"] = None


def run_job_sync(job_id: str):
    asyncio.run(run_job_by_id(job_id))
