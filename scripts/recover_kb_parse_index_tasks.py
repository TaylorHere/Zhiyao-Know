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
import os
from typing import Any

import httpx

API_BASE_URL = os.getenv("YUXI_API_BASE_URL", "http://127.0.0.1:5050")
USERNAME = os.getenv("YUXI_TEST_USERNAME") or os.getenv("YUXI_SUPER_ADMIN_NAME") or "admin"
PASSWORD = os.getenv("YUXI_TEST_PASSWORD") or os.getenv("YUXI_SUPER_ADMIN_PASSWORD") or "Admin@123456"
PRESET_TOKEN = os.getenv("YUXI_TEST_TOKEN") or os.getenv("YUXI_ACCESS_TOKEN")
HTTP_TIMEOUT = float(os.getenv("YUXI_HTTP_TIMEOUT", "120"))

PARSE_RETRY_STATUSES = {"uploaded", "error_parsing", "failed", "parsing"}
INDEX_RETRY_STATUSES = {"parsed", "error_indexing", "indexing"}


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
    ):
        self.dry_run = dry_run
        self.target_db_id = db_id
        self.batch_size = max(1, batch_size)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.qa_separator = qa_separator
        self.token: str | None = None
        self.stats: dict[str, Any] = {
            "databases_total": 0,
            "databases_processed": 0,
            "parse_files": 0,
            "index_files": 0,
            "parse_tasks_submitted": 0,
            "index_tasks_submitted": 0,
            "failed_requests": 0,
        }

    async def login(self) -> bool:
        if PRESET_TOKEN:
            self.token = PRESET_TOKEN
            if await self._validate_token():
                print("✅ 使用预设 token 登录成功")
                return True
            print("⚠️ 预设 token 无效，尝试账号密码登录")

        if self.dry_run:
            self.token = "dry-run-token"
            print("✅ DRY-RUN 模式，跳过真实登录")
            return True

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

    async def process_db(self, db_id: str):
        print(f"\n=== 处理知识库: {db_id} ===")
        try:
            info = await self.get_db_info(db_id)
        except Exception as exc:
            self.stats["failed_requests"] += 1
            print(f"  ❌ 获取知识库信息失败: {exc}")
            return

        files = info.get("files") or {}
        parse_ids: list[str] = []
        index_ids: list[str] = []
        for file_id, meta in files.items():
            status = str((meta or {}).get("status") or "").lower()
            if status in PARSE_RETRY_STATUSES:
                parse_ids.append(file_id)
            elif status in INDEX_RETRY_STATUSES:
                index_ids.append(file_id)

        parse_ids.sort()
        index_ids.sort()
        self.stats["parse_files"] += len(parse_ids)
        self.stats["index_files"] += len(index_ids)

        print(f"  parse 候选: {len(parse_ids)}")
        print(f"  index 候选: {len(index_ids)}")

        for group in batched(parse_ids, self.batch_size):
            await self.submit_parse(db_id, group)

        for group in batched(index_ids, self.batch_size):
            await self.submit_index(db_id, group)

        self.stats["databases_processed"] += 1

    async def run(self):
        print("=" * 68)
        print("知识库任务补跑工具（按文件状态补 parse/index）")
        print("=" * 68)
        print(f"API: {API_BASE_URL}")
        print(f"用户: {USERNAME}")
        print(f"模式: {'DRY-RUN' if self.dry_run else 'EXECUTE'}")
        print(f"批次大小: {self.batch_size}")
        print(f"index 参数: chunk_size={self.chunk_size}, chunk_overlap={self.chunk_overlap}")

        if not await self.login():
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

        for db_id in db_ids:
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
        print(f"请求失败次数: {self.stats['failed_requests']}")


async def main():
    parser = argparse.ArgumentParser(description="服务重启后补跑知识库 parse/index 任务")
    parser.add_argument("--db-id", help="只处理指定知识库 ID")
    parser.add_argument("--dry-run", action="store_true", help="只统计和打印，不实际提交任务")
    parser.add_argument("--batch-size", type=int, default=200, help="每次提交的文件数，默认 200")
    parser.add_argument("--chunk-size", type=int, default=1000, help="index 的 chunk_size，默认 1000")
    parser.add_argument("--chunk-overlap", type=int, default=200, help="index 的 chunk_overlap，默认 200")
    parser.add_argument("--qa-separator", default="", help="index 的 qa_separator，默认空串")
    args = parser.parse_args()

    runner = RecoveryRunner(
        dry_run=args.dry_run,
        db_id=args.db_id,
        batch_size=args.batch_size,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        qa_separator=args.qa_separator,
    )
    await runner.run()


if __name__ == "__main__":
    asyncio.run(main())
