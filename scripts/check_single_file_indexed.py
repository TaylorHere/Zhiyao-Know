#!/usr/bin/env python3
"""
Check whether a single file is truly indexed in the knowledge base (indexed/done).

Example:
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
KB_NAME = os.getenv("YUXI_TEST_KB_NAME", "single_file_import_test_kb")

SUCCESS_STATUSES = {"indexed", "done"}
ERROR_STATUSES = {"error_indexing", "error_parsing", "failed"}


async def get_token() -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{API_BASE_URL}/api/auth/token",
            data={"username": USERNAME, "password": PASSWORD},
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Login failed: {resp.status_code} {resp.text}")
    return resp.json()["access_token"]


async def get_kb_id(token: str, kb_name: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API_BASE_URL}/api/knowledge/databases", headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to get KB list: {resp.status_code} {resp.text}")
    for db in resp.json().get("databases", []):
        if db.get("name") == kb_name:
            return db.get("db_id")
    raise RuntimeError(f"Knowledge base not found: {kb_name}")


async def get_system_defaults(token: str) -> tuple[str, str]:
    """
    Read system default model config from /api/system/config.
    Returns: (embed_model_name, default_model)
    """
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API_BASE_URL}/api/system/config", headers=headers)
    if resp.status_code != 200:
        # fallback values for common local profile
        embed_model = os.getenv("YUXI_EMBED_MODEL", "vllm/Qwen/Qwen3-Embedding-0.6B")
        default_model = os.getenv("YUXI_DEFAULT_MODEL", "vllm-local/Qwen3.5-35B-A3B-FP8")
        print(
            "Warning: failed to load /api/system/config, "
            f"using fallback defaults embed_model={embed_model}, default_model={default_model}"
        )
        return embed_model, default_model

    cfg = resp.json() or {}
    embed_model = cfg.get("embed_model") or os.getenv("YUXI_EMBED_MODEL", "vllm/Qwen/Qwen3-Embedding-0.6B")
    default_model = cfg.get("default_model") or os.getenv("YUXI_DEFAULT_MODEL", "vllm-local/Qwen3.5-35B-A3B-FP8")
    return embed_model, default_model


async def ensure_kb_id(token: str, kb_name: str) -> str:
    headers = {"Authorization": f"Bearer {token}"}

    try:
        return await get_kb_id(token, kb_name)
    except RuntimeError:
        pass

    embed_model_name, default_model = await get_system_defaults(token)
    payload = {
        "database_name": kb_name,
        "description": "Auto-created by check_single_file_indexed.py",
        "embed_model_name": embed_model_name,
        "kb_type": "milvus",
        "additional_params": {},
        "llm_info": {"model": default_model},
    }

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            f"{API_BASE_URL}/api/knowledge/databases",
            headers=headers,
            json=payload,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"Failed to create KB {kb_name}: {resp.status_code} {resp.text}")

    kb_id = resp.json().get("db_id")
    if not kb_id:
        raise RuntimeError(f"Create KB succeeded but db_id missing: {resp.text}")

    print(
        f"Knowledge base created: name={kb_name}, db_id={kb_id}, "
        f"embed_model={embed_model_name}, default_model={default_model}"
    )
    return kb_id


async def get_file_record(token: str, kb_id: str, filename: str) -> dict | None:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API_BASE_URL}/api/knowledge/databases/{kb_id}", headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to get KB detail: {resp.status_code} {resp.text}")

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
    parser = argparse.ArgumentParser(description="Check whether a single file is truly indexed")
    parser.add_argument("--file", required=True, help="Source file path (used to extract filename)")
    parser.add_argument("--kb-name", default=KB_NAME, help="Knowledge base name")
    args = parser.parse_args()

    filename = Path(args.file).name
    if not filename:
        raise RuntimeError(f"Invalid file path: {args.file}")

    print(f"Checking file: {filename}")
    print(f"Target knowledge base: {args.kb_name}")

    token = await get_token()
    kb_id = await ensure_kb_id(token, args.kb_name)
    record = await get_file_record(token, kb_id, filename)
    if not record:
        raise SystemExit("Result: file record not found")

    file_id = record.get("file_id")
    status = (record.get("status") or "").lower()
    ok = status in SUCCESS_STATUSES
    print(f"kb_id={kb_id}, file={filename}, file_id={file_id}, status={status}")
    if ok:
        print("Result: file is indexed")
        return

    if status in ERROR_STATUSES and file_id:
        meta = await get_document_basic_meta(token, kb_id, file_id)
        err = meta.get("error") or meta.get("error_message")
        updated_at = meta.get("updated_at")
        if err:
            print(f"Error detail: {err}")
        if updated_at:
            print(f"Failed at: {updated_at}")

        log_hint = try_tail_api_logs(file_id)
        if log_hint:
            print("Recent related API logs:")
            print(log_hint)
        else:
            print("Manual check: docker compose logs api --tail 300 | grep -E 'Index failed|Failed to parse file|%s'" % file_id)

    raise SystemExit(f"Result: not indexed yet (current status: {status})")


if __name__ == "__main__":
    asyncio.run(main())
