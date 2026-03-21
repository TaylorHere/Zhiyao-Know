#!/usr/bin/env python3
"""
End-to-end single-file import validation:
create/reuse KB -> upload file -> trigger parse/index -> poll final status.

Example:
python3 scripts/check_single_file_indexed.py --file /mnt/usb2/test.pdf --kb-name single_file_import_test_kb
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
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


async def get_system_defaults(token: str) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API_BASE_URL}/api/system/config", headers=headers)
    if resp.status_code != 200:
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
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API_BASE_URL}/api/knowledge/databases", headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to get KB list: {resp.status_code} {resp.text}")

    for db in resp.json().get("databases", []):
        if db.get("name") == kb_name:
            kb_id = db.get("db_id")
            print(f"KB found: name={kb_name}, db_id={kb_id}")
            return kb_id

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
        f"KB created: name={kb_name}, db_id={kb_id}, "
        f"embed_model={embed_model_name}, default_model={default_model}"
    )
    return kb_id


async def get_kb_detail(token: str, kb_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API_BASE_URL}/api/knowledge/databases/{kb_id}", headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to get KB detail: {resp.status_code} {resp.text}")
    return resp.json() or {}


def find_file_record(kb_detail: dict, filename: str) -> dict | None:
    files = kb_detail.get("files") or {}
    for _, info in files.items():
        if info.get("filename") == filename:
            return info
    return None


async def upload_file(token: str, kb_id: str, file_path: Path) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=300) as client:
        with file_path.open("rb") as f:
            files = {"file": (file_path.name, f)}
            resp = await client.post(
                f"{API_BASE_URL}/api/knowledge/files/upload?db_id={kb_id}",
                headers=headers,
                files=files,
            )
    if resp.status_code != 200:
        raise RuntimeError(f"Upload failed: {resp.status_code} {resp.text}")
    data = resp.json() or {}
    file_ref = data.get("file_path") or data.get("minio_path")
    content_hash = data.get("content_hash")
    if not file_ref or not content_hash:
        raise RuntimeError(f"Upload response missing file_path/content_hash: {data}")
    print(f"Upload success: filename={file_path.name}")
    return file_ref, content_hash


async def enqueue_ingest(token: str, kb_id: str, file_ref: str, content_hash: str) -> str | None:
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "items": [file_ref],
        "params": {
            "auto_index": True,
            "content_hashes": {file_ref: content_hash},
        },
    }
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.post(
            f"{API_BASE_URL}/api/knowledge/databases/{kb_id}/documents",
            headers=headers,
            json=payload,
        )
    if resp.status_code != 200:
        raise RuntimeError(f"Ingest enqueue failed: {resp.status_code} {resp.text}")
    task_id = (resp.json() or {}).get("task_id")
    print(f"Ingest task submitted: task_id={task_id}")
    return task_id


async def get_document_basic_meta(token: str, kb_id: str, file_id: str) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{API_BASE_URL}/api/knowledge/databases/{kb_id}/documents/{file_id}/basic", headers=headers)
    if resp.status_code != 200:
        return {}
    return (resp.json() or {}).get("meta") or {}


async def poll_until_final(
    token: str,
    kb_id: str,
    filename: str,
    timeout_seconds: int,
    interval_seconds: int,
) -> dict:
    started = time.monotonic()
    attempt = 0
    while True:
        attempt += 1
        detail = await get_kb_detail(token, kb_id)
        record = find_file_record(detail, filename)
        elapsed = time.monotonic() - started

        if record:
            status = (record.get("status") or "").lower()
            file_id = record.get("file_id")
            print(f"Poll#{attempt}: elapsed={elapsed:.1f}s, file_id={file_id}, status={status}")
            if status in SUCCESS_STATUSES:
                return record
            if status in ERROR_STATUSES:
                return record
        else:
            print(f"Poll#{attempt}: elapsed={elapsed:.1f}s, file record not created yet")

        if elapsed >= timeout_seconds:
            raise TimeoutError(f"Timeout after {timeout_seconds}s waiting for final status")
        await asyncio.sleep(interval_seconds)


async def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end single file import validation")
    parser.add_argument("--file", required=True, help="Absolute file path to import")
    parser.add_argument("--kb-name", default=KB_NAME, help="Knowledge base name")
    parser.add_argument("--timeout", type=int, default=300, help="Polling timeout in seconds")
    parser.add_argument("--interval", type=int, default=5, help="Polling interval in seconds")
    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File does not exist: {file_path}")

    print(f"API base: {API_BASE_URL}")
    print(f"Target KB: {args.kb_name}")
    print(f"Target file: {file_path.name}")

    t0 = time.monotonic()
    token = await get_token()
    kb_id = await ensure_kb_id(token, args.kb_name)

    # Always run full path for new-file validation: upload + ingest + poll.
    file_ref, content_hash = await upload_file(token, kb_id, file_path)
    await enqueue_ingest(token, kb_id, file_ref, content_hash)

    final_record = await poll_until_final(
        token=token,
        kb_id=kb_id,
        filename=file_path.name,
        timeout_seconds=args.timeout,
        interval_seconds=args.interval,
    )

    status = (final_record.get("status") or "").lower()
    file_id = final_record.get("file_id")
    elapsed_all = time.monotonic() - t0
    print(f"Final: kb_id={kb_id}, file_id={file_id}, status={status}, elapsed={elapsed_all:.1f}s")

    if status in SUCCESS_STATUSES:
        print("RESULT: PASS")
        return

    meta = await get_document_basic_meta(token, kb_id, file_id)
    err = meta.get("error") or meta.get("error_message")
    updated_at = meta.get("updated_at")
    if err:
        print(f"Error detail: {err}")
    if updated_at:
        print(f"Failed at: {updated_at}")
    raise SystemExit(f"RESULT: FAIL (status={status})")


if __name__ == "__main__":
    asyncio.run(main())
