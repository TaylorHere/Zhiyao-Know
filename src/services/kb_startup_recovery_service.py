from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import text

from src.knowledge import knowledge_base
from src.knowledge.base import KnowledgeBase
from src.services.task_service import TaskContext, tasker
from src.storage.postgres.manager import pg_manager
from src.utils.datetime_utils import utc_now
from src.utils.logging_config import logger

INTERRUPTED_ERROR_FRAGMENT = "interrupted - process not found in queue"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        return max(minimum, int(raw))
    except (TypeError, ValueError):
        return default


async def _count_active_tasks() -> int:
    async with pg_manager.get_async_session_context() as session:
        result = await session.execute(
            text("SELECT count(1) FROM tasks WHERE status IN ('queued', 'running')")
        )
        return int(result.scalar_one() or 0)


async def _find_interrupted_files(limit: int, lookback_hours: int) -> list[dict[str, Any]]:
    updated_after = utc_now() - timedelta(hours=lookback_hours)
    sql = text(
        """
        SELECT file_id, db_id, status
        FROM knowledge_files
        WHERE status IN ('error_parsing', 'error_indexing')
          AND COALESCE(error_message, '') ILIKE :msg
          AND updated_at >= :updated_after
        ORDER BY updated_at DESC
        LIMIT :limit
        """
    )
    async with pg_manager.get_async_session_context() as session:
        result = await session.execute(
            sql,
            {
                "msg": f"%{INTERRUPTED_ERROR_FRAGMENT}%",
                "updated_after": updated_after,
                "limit": limit,
            },
        )
        return [dict(row._mapping) for row in result.fetchall()]


def _batched(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _enqueue_recovery_task(
    *,
    db_id: str,
    file_ids: list[str],
    task_type: str,
    task_name: str,
    action: Callable[[str, str], Any],
) -> None:
    async def _run(context: TaskContext):
        total = len(file_ids)
        processed_items: list[dict[str, Any]] = []
        await context.set_progress(5.0, "启动恢复任务初始化")
        for idx, file_id in enumerate(file_ids, 1):
            await context.raise_if_cancelled()
            try:
                meta = await action(db_id, file_id)
                processed_items.append(meta)
            except Exception as exc:  # noqa: BLE001
                processed_items.append({"file_id": file_id, "status": "failed", "error": str(exc)})
            await context.set_progress(5.0 + idx / total * 90.0, f"恢复中 {idx}/{total}")
        await context.set_result({"items": processed_items})
        await context.set_progress(100.0, "启动恢复任务完成")
        return {"items": processed_items}

    await tasker.enqueue(
        name=task_name,
        task_type=task_type,
        payload={"db_id": db_id, "file_ids": file_ids},
        coroutine=_run,
    )


async def recover_interrupted_kb_tasks_on_startup() -> None:
    if not _env_bool("YUXI_STARTUP_AUTO_RECOVER_INTERRUPTED", True):
        logger.info("Startup KB recovery disabled by YUXI_STARTUP_AUTO_RECOVER_INTERRUPTED")
        return

    active_task_count = await _count_active_tasks()
    if active_task_count > 0:
        logger.info(
            "Startup KB recovery skipped because there are active tasks in storage: {}",
            active_task_count,
        )
        return

    if active_task_count == 0:
        try:
            deleted = KnowledgeBase._redis_execute("DEL", KnowledgeBase._redis_queue_key)
            if isinstance(deleted, int):
                logger.info("Startup KB recovery: cleared redis processing queue entries={}", deleted)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Startup KB recovery: failed to clear redis queue: {}", exc)

    # Trigger metadata refresh + interrupted status reconciliation in each db
    try:
        dbs = (await knowledge_base.get_databases()).get("databases", [])
        for db in dbs:
            db_id = db.get("db_id")
            if db_id:
                await knowledge_base.get_database_info(db_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Startup KB recovery: failed during metadata reconcile: {}", exc)

    max_files = _env_int("YUXI_STARTUP_RECOVER_MAX_FILES", 20)
    batch_size = _env_int("YUXI_STARTUP_RECOVER_BATCH_SIZE", 10)
    lookback_hours = _env_int("YUXI_STARTUP_RECOVER_LOOKBACK_HOURS", 6)
    rows = await _find_interrupted_files(max_files, lookback_hours)
    if not rows:
        logger.info("Startup KB recovery: no interrupted files to recover")
        return

    parse_by_db: dict[str, list[str]] = defaultdict(list)
    index_by_db: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        file_id = str(row["file_id"])
        db_id = str(row["db_id"])
        status = str(row["status"])
        if status == "error_parsing":
            parse_by_db[db_id].append(file_id)
        elif status == "error_indexing":
            index_by_db[db_id].append(file_id)

    for db_id, file_ids in parse_by_db.items():
        for group in _batched(file_ids, batch_size):
            await _enqueue_recovery_task(
                db_id=db_id,
                file_ids=group,
                task_type="knowledge_startup_recover_parse",
                task_name=f"启动恢复-文档解析 ({db_id})",
                action=lambda d, f: knowledge_base.parse_file(d, f, operator_id="system"),
            )

    for db_id, file_ids in index_by_db.items():
        for group in _batched(file_ids, batch_size):
            await _enqueue_recovery_task(
                db_id=db_id,
                file_ids=group,
                task_type="knowledge_startup_recover_index",
                task_name=f"启动恢复-文档入库 ({db_id})",
                action=lambda d, f: knowledge_base.index_file(d, f, operator_id="system"),
            )

    logger.info(
        "Startup KB recovery scheduled parse_files={}, index_files={}, max_files={}, batch_size={}",
        sum(len(v) for v in parse_by_db.values()),
        sum(len(v) for v in index_by_db.values()),
        max_files,
        batch_size,
    )
