#!/usr/bin/env python3
"""
服务重启后，按文件状态自动补跑知识库解析/入库任务。

规则：
- parse 补跑状态: uploaded, error_parsing, failed, parsing
- index 补跑状态: parsed, error_indexing, indexing

用法：
    python scripts/recover_kb_parse_index_tasks.py
    python scripts/recover_kb_parse_index_tasks.py --db-id kb_xxx
    python scripts/recover_kb_parse_index_tasks.py --dry-run
"""

import argparse
import asyncio
import fcntl
import os
from collections import Counter
from contextlib import contextmanager
from typing import Any

import httpx

API_BASE_URL = os.getenv("YUXI_API_BASE_URL", "http://127.0.0.1:5050")
USERNAME = os.getenv("YUXI_TEST_USERNAME") or os.getenv("YUXI_SUPER_ADMIN_NAME") or "admin"
PASSWORD = os.getenv("YUXI_TEST_PASSWORD") or os.getenv("YUXI_SUPER_ADMIN_PASSWORD") or "Admin@123456"
PRESET_TOKEN = os.getenv("YUXI_TEST_TOKEN") or os.getenv("YUXI_ACCESS_TOKEN")
HTTP_TIMEOUT = float(os.getenv("YUXI_HTTP_TIMEOUT", "120"))

PARSE_RETRY_STATUSES = {"uploaded", "error_parsing", "failed", "parsing"}
INDEX_RETRY_STATUSES = {"parsed", "error_indexing", "indexing"}
ABNORMAL_STATUSES = PARSE_RETRY_STATUSES | INDEX_RETRY_STATUSES


def batched(items: list[str], size: int) -> list[list[str]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


class RecoveryRunner:
    def __init__(
        self,
        dry_run: bool,
        db_id: str | None,
        batch_size: int,
        chunk_size: int,
        chunk_overlap: int,
        qa_separator: str,
        use_reparse_index: bool,
    ):
        self.dry_run = dry_run
        self.target_db_id = db_id
        self.batch_size = max(1, batch_size)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.qa_separator = qa_separator
        self.use_reparse_index = use_reparse_index
        self.token: str | None = None
        self.stats: dict[str, Any] = {
            "databases_total": 0,
            "databases_processed": 0,
            "parse_files": 0,
            "index_files": 0,
            "parse_tasks_submitted": 0,
            "index_tasks_submitted": 0,
            "reparse_index_tasks_submitted": 0,
            "failed_requests": 0,
        }

    async def login(self) -> bool:
        if self.dry_run:
            print("✅ DRY-RUN 模式：不会提交任务，但仍会登录以读取知识库状态")

        if PRESET_TOKEN and not self.dry_run:
            self.token = PRESET_TOKEN
            if await self._validate_token():
                print("✅ 使用预设 token 登录成功")
                return True
            print("⚠️ 预设 token 无效，尝试账号密码登录")

        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                resp = await client.post(
                    f"{API_BASE_URL}/api/auth/token",
                    data={"username": USERNAME, "password": PASSWORD},
                )
            if resp.status_code == 200:
                self.token = (resp.json() or {}).get("access_token")
                if self.token:
                    print(f"✅ 登录成功: {USERNAME}")
                    return True
            print(f"❌ 登录失败: HTTP {resp.status_code}, {resp.text[:200]}")
            return False
        except Exception as exc:
            print(f"❌ 登录异常: {exc}")
            return False

    async def _validate_token(self) -> bool:
        if not self.token:
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    f"{API_BASE_URL}/api/auth/me",
                    headers={"Authorization": f"Bearer {self.token}"},
                )
            return resp.status_code == 200
        except Exception:
            return False

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    async def count_active_knowledge_tasks(self, limit: int = 100) -> int:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{API_BASE_URL}/api/tasks",
                headers=self._headers(),
                params={"limit": max(1, min(limit, 100))},
            )
        if resp.status_code != 200:
            raise RuntimeError(f"获取任务列表失败: HTTP {resp.status_code}, {resp.text[:200]}")
        data = resp.json() or {}
        tasks = data.get("tasks") or []
        active_statuses = {"pending", "running"}
        return sum(
            1
            for task in tasks
            if str(task.get("status") or "").lower() in active_statuses
            and str(task.get("type") or "").startswith("knowledge_")
        )

    async def list_db_ids(self) -> list[str]:
        if self.target_db_id:
            return [self.target_db_id]
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{API_BASE_URL}/api/knowledge/databases",
                headers=self._headers(),
            )
        if resp.status_code != 200:
            raise RuntimeError(f"获取知识库列表失败: HTTP {resp.status_code}, {resp.text[:200]}")
        data = resp.json() or {}
        return [d.get("db_id") for d in data.get("databases", []) if d.get("db_id")]

    async def get_db_info(self, db_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(
                f"{API_BASE_URL}/api/knowledge/databases/{db_id}",
                headers=self._headers(),
            )
        if resp.status_code != 200:
            raise RuntimeError(f"获取知识库详情失败: db_id={db_id}, HTTP {resp.status_code}, {resp.text[:200]}")
        return resp.json() or {}

    async def submit_parse(self, db_id: str, file_ids: list[str]) -> bool:
        if self.dry_run:
            print(f"  [DRY-RUN] parse files={len(file_ids)}")
            return True
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{API_BASE_URL}/api/knowledge/databases/{db_id}/documents/parse",
                headers=self._headers(),
                json=file_ids,
            )
        if resp.status_code == 200:
            task_id = (resp.json() or {}).get("task_id", "unknown")
            self.stats["parse_tasks_submitted"] += 1
            print(f"  ✅ parse 任务已提交: task_id={task_id}, files={len(file_ids)}")
            return True
        self.stats["failed_requests"] += 1
        print(f"  ❌ parse 提交失败: HTTP {resp.status_code}, {resp.text[:200]}")
        return False

    async def submit_index(self, db_id: str, file_ids: list[str]) -> bool:
        if self.dry_run:
            print(f"  [DRY-RUN] index files={len(file_ids)}")
            return True
        payload = {
            "file_ids": file_ids,
            "params": {
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
                "qa_separator": self.qa_separator,
            },
        }
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{API_BASE_URL}/api/knowledge/databases/{db_id}/documents/index",
                headers=self._headers(),
                json=payload,
            )
        if resp.status_code == 200:
            task_id = (resp.json() or {}).get("task_id", "unknown")
            self.stats["index_tasks_submitted"] += 1
            print(f"  ✅ index 任务已提交: task_id={task_id}, files={len(file_ids)}")
            return True
        self.stats["failed_requests"] += 1
        print(f"  ❌ index 提交失败: HTTP {resp.status_code}, {resp.text[:200]}")
        return False

    async def submit_reparse_index(self, db_id: str, file_ids: list[str]) -> bool:
        if self.dry_run:
            print(f"  [DRY-RUN] reparse-index files={len(file_ids)}")
            return True
        payload = {
            "file_ids": file_ids,
            "params": {
                "chunk_size": self.chunk_size,
                "chunk_overlap": self.chunk_overlap,
                "qa_separator": self.qa_separator,
            },
        }
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.post(
                f"{API_BASE_URL}/api/knowledge/databases/{db_id}/documents/reparse-index",
                headers=self._headers(),
                json=payload,
            )
        if resp.status_code == 200:
            task_id = (resp.json() or {}).get("task_id", "unknown")
            self.stats["reparse_index_tasks_submitted"] += 1
            print(f"  ✅ reparse-index 任务已提交: task_id={task_id}, files={len(file_ids)}")
            return True
        self.stats["failed_requests"] += 1
        print(f"  ❌ reparse-index 提交失败: HTTP {resp.status_code}, {resp.text[:200]}")
        return False

    async def process_db(self, db_id: str):
        print(f"\n=== 处理知识库: {db_id} ===")
        try:
            scan = await self.scan_db(db_id)
        except Exception as exc:
            self.stats["failed_requests"] += 1
            print(f"  ❌ 获取知识库信息失败: {exc}")
            return

        parse_ids = [item["file_id"] for item in scan["parse_items"]]
        index_ids = [item["file_id"] for item in scan["index_items"]]

        parse_ids.sort()
        index_ids.sort()
        self.stats["parse_files"] += len(parse_ids)
        self.stats["index_files"] += len(index_ids)

        print(f"  parse 候选: {len(parse_ids)}")
        print(f"  index 候选: {len(index_ids)}")

        if self.use_reparse_index:
            # 智能分流：
            # - 需要重解析的文件：走 reparse-index（解析+入库）
            # - 已解析/仅入库异常文件：直接走 index
            for group in batched(parse_ids, self.batch_size):
                await self.submit_reparse_index(db_id, group)
            for group in batched(index_ids, self.batch_size):
                await self.submit_index(db_id, group)
        else:
            for group in batched(parse_ids, self.batch_size):
                await self.submit_parse(db_id, group)
            for group in batched(index_ids, self.batch_size):
                await self.submit_index(db_id, group)

        self.stats["databases_processed"] += 1

    async def scan_db(self, db_id: str) -> dict[str, Any]:
        info = await self.get_db_info(db_id)
        kb_name = info.get("name") or "-"
        files = info.get("files") or {}

        parse_items: list[dict[str, str]] = []
        index_items: list[dict[str, str]] = []
        status_counter = Counter()

        for file_id, meta in files.items():
            status = str((meta or {}).get("status") or "").lower()
            if status not in ABNORMAL_STATUSES:
                continue
            filename = (
                (meta or {}).get("filename")
                or (meta or {}).get("original_filename")
                or "-"
            )
            item = {"file_id": file_id, "filename": filename, "status": status}
            status_counter[status] += 1
            if status in PARSE_RETRY_STATUSES:
                parse_items.append(item)
            else:
                index_items.append(item)

        parse_items.sort(key=lambda x: x["file_id"])
        index_items.sort(key=lambda x: x["file_id"])
        return {
            "db_id": db_id,
            "kb_name": kb_name,
            "parse_items": parse_items,
            "index_items": index_items,
            "status_counter": status_counter,
        }

    async def run(self, *, skip_if_active_knowledge_tasks: bool, active_task_limit: int):
        print("=" * 68)
        print("知识库任务补跑工具（按文件状态补 parse/index）")
        print("=" * 68)
        print(f"API: {API_BASE_URL}")
        print(f"用户: {USERNAME}")
        print(f"模式: {'DRY-RUN' if self.dry_run else 'EXECUTE'}")
        print(
            "处理方式: SMART(解析失败->reparse-index, 已解析->index)"
            if self.use_reparse_index
            else "处理方式: PARSE+INDEX(分离)"
        )
        print(f"批次大小: {self.batch_size}")
        print(f"index 参数: chunk_size={self.chunk_size}, chunk_overlap={self.chunk_overlap}")

        if not await self.login():
            return

        if skip_if_active_knowledge_tasks:
            try:
                active_knowledge_tasks = await self.count_active_knowledge_tasks(limit=active_task_limit)
            except Exception as exc:
                print(f"❌ 查询当前任务状态失败: {exc}")
                return
            if active_knowledge_tasks > 0:
                print(f"⏭️ 检测到活跃知识库任务 {active_knowledge_tasks} 个，跳过本次补跑")
                return

        try:
            db_ids = await self.list_db_ids()
        except Exception as exc:
            print(f"❌ 获取知识库列表失败: {exc}")
            return

        self.stats["databases_total"] = len(db_ids)
        if not db_ids:
            print("没有可处理的知识库")
            return

        # 1) 先扫描并打印当前异常状态统计
        all_scans: list[dict[str, Any]] = []
        global_counter = Counter()
        total_abnormal_files = 0
        for db_id in db_ids:
            try:
                scan = await self.scan_db(db_id)
            except Exception as exc:
                self.stats["failed_requests"] += 1
                print(f"⚠️ 扫描失败: {db_id}, err={exc}")
                continue
            abnormal_count = len(scan["parse_items"]) + len(scan["index_items"])
            if abnormal_count == 0:
                continue
            all_scans.append(scan)
            total_abnormal_files += abnormal_count
            global_counter.update(scan["status_counter"])

        print("\n" + "=" * 68)
        print("异常状态预检查")
        print("=" * 68)
        print(f"异常知识库数: {len(all_scans)}")
        print(f"异常文件总数: {total_abnormal_files}")
        if global_counter:
            print("状态分布:")
            for status, cnt in sorted(global_counter.items(), key=lambda x: (-x[1], x[0])):
                print(f"  - {status:16s} {cnt}")

        if all_scans:
            print("\n涉及知识库与文件:")
            for scan in all_scans:
                db_id = scan["db_id"]
                kb_name = scan["kb_name"]
                items = scan["parse_items"] + scan["index_items"]
                print(f"\n- [{db_id}] {kb_name} (异常文件: {len(items)})")
                for item in items:
                    print(f"    {item['status']:16s} {item['filename']}")
        else:
            print("未发现需要补跑的文件。")
            return

        print("\n开始逐一处理异常知识库...")

        for db_id in db_ids:
            # 只处理扫描出异常的知识库
            if not any(s["db_id"] == db_id for s in all_scans):
                continue
            await self.process_db(db_id)

        print("\n" + "=" * 68)
        print("执行完成")
        print("=" * 68)
        print(f"知识库总数: {self.stats['databases_total']}")
        print(f"知识库处理数: {self.stats['databases_processed']}")
        print(f"parse 文件数: {self.stats['parse_files']}")
        print(f"index 文件数: {self.stats['index_files']}")
        print(f"parse 任务提交数: {self.stats['parse_tasks_submitted']}")
        print(f"index 任务提交数: {self.stats['index_tasks_submitted']}")
        print(f"reparse-index 任务提交数: {self.stats['reparse_index_tasks_submitted']}")
        print(f"请求失败次数: {self.stats['failed_requests']}")


async def main():
    parser = argparse.ArgumentParser(description="服务重启后补跑知识库 parse/index 任务")
    parser.add_argument("--db-id", help="只处理指定知识库 ID")
    parser.add_argument("--dry-run", action="store_true", help="只统计和打印，不实际提交任务")
    parser.add_argument("--batch-size", type=int, default=200, help="每次提交的文件数，默认 200")
    parser.add_argument("--chunk-size", type=int, default=1000, help="index 的 chunk_size，默认 1000")
    parser.add_argument("--chunk-overlap", type=int, default=200, help="index 的 chunk_overlap，默认 200")
    parser.add_argument("--qa-separator", default="", help="index 的 qa_separator，默认空串")
    parser.add_argument(
        "--legacy-separate-submit",
        action="store_true",
        help="使用旧逻辑：分别提交 parse/index（默认关闭，默认走 reparse-index 一体）",
    )
    parser.add_argument(
        "--ignore-active-knowledge-tasks",
        action="store_true",
        help="忽略活跃知识库任务检测（默认检测到 pending/running 的 knowledge_* 任务会跳过）",
    )
    parser.add_argument(
        "--active-task-limit",
        type=int,
        default=100,
        help="任务检测接口拉取数量上限，默认 100",
    )
    parser.add_argument(
        "--lock-file",
        default="/tmp/yuxi_kb_recover.lock",
        help="互斥锁文件路径，默认 /tmp/yuxi_kb_recover.lock",
    )
    parser.add_argument("--no-lock", action="store_true", help="关闭进程互斥锁（不推荐）")
    args = parser.parse_args()

    runner = RecoveryRunner(
        dry_run=args.dry_run,
        db_id=args.db_id,
        batch_size=args.batch_size,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        qa_separator=args.qa_separator,
        use_reparse_index=not args.legacy_separate_submit,
    )
    @contextmanager
    def single_instance_lock(path: str):
        lock_fd = open(path, "w")
        try:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock_fd.close()
            raise RuntimeError(f"已有恢复脚本在运行（lock={path}）")
        try:
            yield
        finally:
            fcntl.flock(lock_fd.fileno(), fcntl.LOCK_UN)
            lock_fd.close()

    if args.no_lock:
        await runner.run(
            skip_if_active_knowledge_tasks=not args.ignore_active_knowledge_tasks,
            active_task_limit=args.active_task_limit,
        )
        return

    try:
        with single_instance_lock(args.lock_file):
            await runner.run(
                skip_if_active_knowledge_tasks=not args.ignore_active_knowledge_tasks,
                active_task_limit=args.active_task_limit,
            )
    except RuntimeError as exc:
        print(f"⏭️ {exc}")


if __name__ == "__main__":
    asyncio.run(main())
