#!/usr/bin/env python3
"""
检查单个文件是否已真正入库（indexed/done）

默认配置：
- API: http://127.0.0.1:5050
- 用户名: admin
- 密码: 1234hbnj
- 知识库名: 单文件导入测试库

示例：
python3 scripts/check_single_file_indexed.py --file /mnt/usb2/test.pdf
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
from pathlib import Path

import httpx

API_BASE_URL = os.getenv("YUXI_API_BASE_URL", "http://127.0.0.1:5050")
USERNAME = os.getenv("YUXI_TEST_USERNAME", "admin")
PASSWORD = os.getenv("YUXI_TEST_PASSWORD", "Admin@123456")
KB_NAME = os.getenv("YUXI_TEST_KB_NAME", "单文件导入测试库")

SUCCESS_STATUSES = {"indexed", "done"}
ERROR_STATUSES = {"error_indexing", "error_parsing", "failed"}


async def get_token() -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{API_BASE_URL}/api/auth/token",
            data={"username": USERNAME, "password": PASSWORD},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"登录失败: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


async def get_kb_id(token: str, kb_name: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API_BASE_URL}/api/knowledge/databases", headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"获取知识库列表失败: {resp.status_code} {resp.text}")
    for db in resp.json().get("databases", []):
        if db.get("name") == kb_name:
            return db.get("db_id")
    raise RuntimeError(f"未找到知识库: {kb_name}")


async def get_file_record(token: str, kb_id: str, filename: str) -> dict | None:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API_BASE_URL}/api/knowledge/databases/{kb_id}", headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"获取知识库详情失败: {resp.status_code} {resp.text}")

    files = (resp.json() or {}).get("files") or {}
    for _, info in files.items():
        if info.get("filename") == filename:
            return info
    return None


async def get_document_basic_meta(token: str, kb_id: str, file_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API_BASE_URL}/api/knowledge/databases/{kb_id}/documents/{file_id}/basic", headers=headers)
    if resp.status_code != 200:
        return {}
    return (resp.json() or {}).get("meta") or {}


def try_tail_api_logs(file_id: str, max_lines: int = 200) -> str:
    cmd = ["docker", "compose", "logs", "api", "--tail", str(max_lines)]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        return ""
    lines = []
    for ln in (proc.stdout or "").splitlines():
        if file_id in ln or "Index failed" in ln or "Failed to parse file" in ln:
            lines.append(ln)
    return "\n".join(lines[-20:])


async def main() -> None:
    parser = argparse.ArgumentParser(description="检查单个文件是否已真正入库")
    parser.add_argument("--file", required=True, help="原始文件路径（用于提取文件名）")
    parser.add_argument("--kb-name", default=KB_NAME, help="知识库名称，默认 单文件导入测试库")
    args = parser.parse_args()

    filename = Path(args.file).name
    if not filename:
        raise RuntimeError(f"无效文件路径: {args.file}")

    print(f"检查文件: {filename}")
    print(f"目标知识库: {args.kb_name}")

    token = await get_token()
    kb_id = await get_kb_id(token, args.kb_name)
    record = await get_file_record(token, kb_id, filename)
    if not record:
        raise SystemExit("结果: 未找到该文件记录")

    file_id = record.get("file_id")
    status = (record.get("status") or "").lower()
    ok = status in SUCCESS_STATUSES
    print(f"kb_id={kb_id}, file={filename}, file_id={file_id}, status={status}")
    if ok:
        print("结果: 已真正入库")
        return

    if status in ERROR_STATUSES and file_id:
        meta = await get_document_basic_meta(token, kb_id, file_id)
        err = meta.get("error") or meta.get("error_message")
        updated_at = meta.get("updated_at")
        if err:
            print(f"错误详情: {err}")
        if updated_at:
            print(f"失败时间: {updated_at}")

        log_hint = try_tail_api_logs(file_id)
        if log_hint:
            print("最近相关日志（api）：")
            print(log_hint)
        else:
            print("可手工排查：docker compose logs api --tail 300 | grep -E 'Index failed|Failed to parse file|%s'" % file_id)

    raise SystemExit(f"结果: 尚未真正入库（当前状态: {status}）")


if __name__ == "__main__":
    asyncio.run(main())
