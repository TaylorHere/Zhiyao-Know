#!/usr/bin/env python3
"""
独立知识库任务 Worker：
- 从 tasks 表拉取 pending 的 knowledge_* 任务
- 执行解析/入库/重解析入库
- 持续更新任务状态与进度
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from sqlalchemy import select

from src import knowledge_base
from src.storage.postgres.manager import pg_manager
from src.storage.postgres.models_business import TaskRecord
from src.utils import logger
from src.utils.datetime_utils import utc_now_naive

KB_TASK_TYPES = {"knowledge_parse", "knowledge_index", "knowledge_reparse_index"}
DEFAULT_OPERATOR_ID = os.getenv("YUXI_KB_WORKER_OPERATOR_ID", "system")
POLL_INTERVAL_SECONDS = float(os.getenv("YUXI_KB_WORKER_POLL_INTERVAL", "2"))


class TaskCancelled(Exception):
    pass


def _resolve_index_concurrency(params: dict | None, default: int = 2) -> int:
    if params and "index_concurrency" in params:
        raw = params.get("index_concurrency")
    else:
        raw = os.getenv("YUXI_INDEX_CONCURRENCY", str(default))
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return default


def _meta_of(data: dict | None) -> dict:
    if isinstance(data, dict) and isinstance(data.get("meta"), dict):
        return data["meta"]
    return data or {}


async def _claim_one_task() -> dict[str, Any] | None:
    async with pg_manager.get_async_session_context() as session:
        result = await session.execute(
            select(TaskRecord)
            .where(TaskRecord.status == "pending", TaskRecord.type.in_(KB_TASK_TYPES))
            .order_by(TaskRecord.created_at.asc())
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if not record:
            return None
        record.status = "running"
        record.progress = 0.0
        record.message = "任务开始执行"
        record.started_at = utc_now_naive()
        record.updated_at = utc_now_naive()
        return {
            "id": record.id,
            "type": record.type,
            "payload": record.payload or {},
        }


async def _update_task(task_id: str, **fields: Any) -> None:
    async with pg_manager.get_async_session_context() as session:
        result = await session.execute(select(TaskRecord).where(TaskRecord.id == task_id).limit(1))
        record = result.scalar_one_or_none()
        if not record:
            return
        for key, value in fields.items():
            setattr(record, key, value)
        record.updated_at = utc_now_naive()


async def _is_cancel_requested(task_id: str) -> bool:
    async with pg_manager.get_async_session_context() as session:
        result = await session.execute(select(TaskRecord.cancel_requested).where(TaskRecord.id == task_id).limit(1))
        return bool(result.scalar_one_or_none() or 0)


async def _raise_if_cancel_requested(task_id: str) -> None:
    if await _is_cancel_requested(task_id):
        raise TaskCancelled("任务被取消")


async def _run_parse(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    db_id = str(payload.get("db_id") or "")
    file_ids = [str(file_id) for file_id in (payload.get("file_ids") or [])]
    operator_id = str(payload.get("operator_id") or DEFAULT_OPERATOR_ID)
    total = len(file_ids)
    processed_items: list[dict[str, Any]] = []

    if not db_id or not file_ids:
        return {"items": []}

    await _update_task(task_id, progress=5.0, message="准备解析文档")

    for idx, file_id in enumerate(file_ids, 1):
        await _raise_if_cancel_requested(task_id)
        progress = 5.0 + (idx / total) * 90.0
        await _update_task(task_id, progress=progress, message=f"正在解析第 {idx}/{total} 个文档")
        try:
            result = await knowledge_base.parse_file(db_id, file_id, operator_id=operator_id)
            processed_items.append(result)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "event=kb_parse_failed db_id={} file_id={} error_type={} error={}",
                db_id,
                file_id,
                type(exc).__name__,
                str(exc),
            )
            processed_items.append({"file_id": file_id, "status": "failed", "error": str(exc)})

    return {"items": processed_items}


async def _run_index(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    db_id = str(payload.get("db_id") or "")
    file_ids = [str(file_id) for file_id in (payload.get("file_ids") or [])]
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    operator_id = str(payload.get("operator_id") or DEFAULT_OPERATOR_ID)
    processed_items: list[dict[str, Any]] = []

    if not db_id or not file_ids:
        return {"items": []}

    await _update_task(task_id, progress=5.0, message="准备入库文档")

    param_update_failed: set[str] = set()
    if params:
        for file_id in file_ids:
            await _raise_if_cancel_requested(task_id)
            try:
                await knowledge_base.update_file_params(db_id, file_id, params, operator_id=operator_id)
            except Exception as exc:  # noqa: BLE001
                param_update_failed.add(file_id)
                processed_items.append({"file_id": file_id, "status": "failed", "error": f"参数更新失败: {exc}"})

    candidate_file_ids = [file_id for file_id in file_ids if file_id not in param_update_failed]
    total_candidates = len(candidate_file_ids)
    if total_candidates == 0:
        return {"items": processed_items}

    index_concurrency = _resolve_index_concurrency(params)
    await _update_task(task_id, message=f"并发入库中（并发 {index_concurrency}）")
    semaphore = asyncio.Semaphore(index_concurrency)
    progress_lock = asyncio.Lock()
    done_count = 0

    async def _index_one(file_id: str) -> dict[str, Any]:
        nonlocal done_count
        async with semaphore:
            await _raise_if_cancel_requested(task_id)
            try:
                return await knowledge_base.index_file(db_id, file_id, operator_id=operator_id)
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "event=kb_index_failed db_id={} file_id={} error_type={} error={}",
                    db_id,
                    file_id,
                    type(exc).__name__,
                    str(exc),
                )
                return {"file_id": file_id, "status": "failed", "error": str(exc)}
            finally:
                async with progress_lock:
                    done_count += 1
                    progress = 5.0 + (done_count / total_candidates) * 90.0
                    await _update_task(task_id, progress=progress, message=f"正在入库第 {done_count}/{total_candidates} 个文档")

    processed_items.extend(await asyncio.gather(*[_index_one(file_id) for file_id in candidate_file_ids]))
    return {"items": processed_items}


async def _run_reparse_index(task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    db_id = str(payload.get("db_id") or "")
    file_ids = [str(file_id) for file_id in (payload.get("file_ids") or [])]
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    operator_id = str(payload.get("operator_id") or DEFAULT_OPERATOR_ID)
    parse_allowed_statuses = {"uploaded", "error_parsing", "failed"}
    index_allowed_statuses = {"parsed", "error_indexing", "done", "indexed"}
    processing_statuses = {"processing", "waiting", "parsing", "indexing"}
    total = len(file_ids)

    if not db_id or total == 0:
        return {"items": []}

    await _update_task(task_id, progress=5.0, message="准备重解析并入库")
    index_concurrency = _resolve_index_concurrency(params)
    await _update_task(task_id, message=f"并发重解析入库中（并发 {index_concurrency}）")

    semaphore = asyncio.Semaphore(index_concurrency)
    progress_lock = asyncio.Lock()
    done_count = 0

    async def _reparse_index_one(file_id: str) -> dict[str, Any]:
        nonlocal done_count
        async with semaphore:
            await _raise_if_cancel_requested(task_id)
            try:
                try:
                    file_meta = _meta_of(await knowledge_base.get_file_basic_info(db_id, file_id))
                except Exception:
                    return {"file_id": file_id, "status": "failed", "error": "文件不存在或不属于当前知识库"}

                status = file_meta.get("status")
                if status in processing_statuses:
                    return {"file_id": file_id, "status": "failed", "error": f"文件正在处理中: {status}"}

                # "重解析并入库" 的语义应保证先有最新 markdown：
                # 1) 常规可解析状态（uploaded/error_parsing/failed）
                # 2) 元数据异常：状态允许入库但 markdown_file 丢失
                # 若不先解析，后续 index_file 会报 "no markdown_file"。
                if status in parse_allowed_statuses or not file_meta.get("markdown_file"):
                    parsed_meta = _meta_of(await knowledge_base.parse_file(db_id, file_id, operator_id=operator_id))
                    status = parsed_meta.get("status")

                if status not in index_allowed_statuses:
                    return {"file_id": file_id, "status": "failed", "error": f"文件状态不支持入库: {status}"}

                if params:
                    await knowledge_base.update_file_params(db_id, file_id, params, operator_id=operator_id)
                return _meta_of(await knowledge_base.index_file(db_id, file_id, operator_id=operator_id))
            except Exception as exc:  # noqa: BLE001
                logger.error(
                    "event=kb_reparse_index_failed db_id={} file_id={} error_type={} error={}",
                    db_id,
                    file_id,
                    type(exc).__name__,
                    str(exc),
                )
                return {"file_id": file_id, "status": "failed", "error": str(exc)}
            finally:
                async with progress_lock:
                    done_count += 1
                    progress = 5.0 + (done_count / total) * 90.0
                    await _update_task(task_id, progress=progress, message=f"正在处理第 {done_count}/{total} 个文档")

    return {"items": await asyncio.gather(*[_reparse_index_one(file_id) for file_id in file_ids])}


async def _run_task(task: dict[str, Any]) -> None:
    task_id = task["id"]
    task_type = str(task["type"])
    payload = task["payload"] if isinstance(task["payload"], dict) else {}

    try:
        if task_type == "knowledge_parse":
            result = await _run_parse(task_id, payload)
            failed_count = len([item for item in result.get("items", []) if "error" in item])
            message = f"解析完成，失败 {failed_count} 个"
        elif task_type == "knowledge_index":
            result = await _run_index(task_id, payload)
            failed_count = len([item for item in result.get("items", []) if "error" in item])
            message = f"入库完成，失败 {failed_count} 个"
        elif task_type == "knowledge_reparse_index":
            result = await _run_reparse_index(task_id, payload)
            failed_count = len([item for item in result.get("items", []) if "error" in item or item.get("status") == "failed"])
            message = f"重解析并入库完成，失败 {failed_count} 个"
        else:
            raise RuntimeError(f"unsupported knowledge task type: {task_type}")

        await _update_task(
            task_id,
            status="success",
            progress=100.0,
            message=message,
            result=result,
            error=None,
            completed_at=utc_now_naive(),
        )
    except TaskCancelled:
        await _update_task(
            task_id,
            status="cancelled",
            progress=100.0,
            message="任务被取消",
            completed_at=utc_now_naive(),
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("KB worker task failed: task_id={}, type={}, err={}", task_id, task_type, exc)
        await _update_task(
            task_id,
            status="failed",
            progress=100.0,
            message="任务执行失败",
            error=str(exc),
            completed_at=utc_now_naive(),
        )


async def main() -> None:
    pg_manager.initialize()
    await pg_manager.create_business_tables()
    await pg_manager.ensure_knowledge_schema()
    await knowledge_base.initialize()
    logger.info("KB worker started. poll_interval={}s", POLL_INTERVAL_SECONDS)

    while True:
        task = await _claim_one_task()
        if not task:
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue
        await _run_task(task)


if __name__ == "__main__":
    asyncio.run(main())
