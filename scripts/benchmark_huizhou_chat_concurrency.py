#!/usr/bin/env python3
"""
使用 CSV 中的 query 字段并发压测 HuizhouPowerQAAgent。

特点：
1) 默认一次性全量并发发出（无并发限流）
2) 记录每个请求的细粒度指标（HTTP 状态、TTFT、总耗时、流式行数、是否 finished、错误信息等）
3) 输出详细报告：JSON（完整）、CSV（明细）、TXT（摘要）
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import statistics
import subprocess
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp


@dataclass
class RequestResult:
    index: int
    query: str
    request_started_at: str
    request_ended_at: str
    http_status: int | None
    ok: bool
    finished: bool
    total_ms: float
    ttft_ms: float | None
    stream_lines: int
    response_chars: int
    answer_preview: str
    error_type: str | None
    error_message: str | None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * p
    f = int(k)
    c = min(f + 1, len(ordered) - 1)
    if f == c:
        return ordered[f]
    return ordered[f] + (ordered[c] - ordered[f]) * (k - f)


def read_queries(csv_path: Path, query_col: str, limit: int | None) -> list[str]:
    queries: list[str] = []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            q = (row.get(query_col) or "").strip()
            if not q:
                continue
            queries.append(q)
            if limit is not None and len(queries) >= limit:
                break
    return queries


def login_by_password(api_base: str, username: str, password: str, timeout: int) -> str:
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode({"username": username, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base}/api/auth/token",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8", errors="ignore"))
    token = body.get("access_token")
    if not token:
        raise RuntimeError(f"登录成功但未返回 access_token: {body}")
    return token


def token_from_docker_compose() -> str:
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        "from server.utils.auth_utils import AuthUtils; print(AuthUtils.create_access_token({'sub':'1'}))",
    ]
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"docker 生成 token 失败: {proc.stderr.strip()}")
    lines = [x.strip() for x in (proc.stdout or "").splitlines() if x.strip()]
    if not lines:
        raise RuntimeError("docker 生成 token 失败: 输出为空")
    return lines[-1]


def resolve_token(args: argparse.Namespace) -> tuple[str, str]:
    if args.token:
        return args.token, "cli_token"

    username = args.username or os.getenv("YUXI_SUPER_ADMIN_NAME")
    password = args.password or os.getenv("YUXI_SUPER_ADMIN_PASSWORD")
    if username and password:
        try:
            return login_by_password(args.api_base, username, password, args.request_timeout_sec), "password_login"
        except Exception as e:
            print(f"[WARN] 账号密码换 token 失败，回退 docker compose 生成 token: {e}")

    return token_from_docker_compose(), "docker_compose"


async def run_one(
    session: aiohttp.ClientSession,
    api_base: str,
    agent_id: str,
    agent_config_id: int,
    query: str,
    idx: int,
    token: str,
    timeout_sec: int,
    save_full_answer: bool,
) -> RequestResult:
    url = f"{api_base}/api/chat/agent/{agent_id}"
    payload = {
        "query": query,
        "config": {"agent_config_id": agent_config_id},
        "meta": {},
    }

    t0 = time.perf_counter()
    request_started_at = now_iso()
    first_chunk_ts: float | None = None
    http_status: int | None = None
    stream_lines = 0
    response_chars = 0
    finished = False
    answer_parts: list[str] = []

    try:
        async with session.post(url, json=payload) as resp:
            http_status = resp.status
            buf = ""
            async for raw in resp.content.iter_chunked(8192):
                if first_chunk_ts is None:
                    first_chunk_ts = time.perf_counter()
                buf += raw.decode("utf-8", errors="ignore")
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    stream_lines += 1

                    try:
                        obj = json.loads(line)
                    except Exception:
                        continue

                    part = obj.get("response")
                    if isinstance(part, str) and part:
                        response_chars += len(part)
                        if save_full_answer:
                            answer_parts.append(part)
                        elif len("".join(answer_parts)) < 600:
                            answer_parts.append(part)

                    if obj.get("status") == "finished":
                        finished = True

            # 处理末尾没有换行符的最后一段
            tail = buf.strip()
            if tail:
                stream_lines += 1
                try:
                    obj = json.loads(tail)
                    part = obj.get("response")
                    if isinstance(part, str) and part:
                        response_chars += len(part)
                        if save_full_answer:
                            answer_parts.append(part)
                        elif len("".join(answer_parts)) < 600:
                            answer_parts.append(part)
                    if obj.get("status") == "finished":
                        finished = True
                except Exception:
                    pass

        t1 = time.perf_counter()
        total_ms = (t1 - t0) * 1000
        ttft_ms = (first_chunk_ts - t0) * 1000 if first_chunk_ts else None
        answer_preview = "".join(answer_parts).replace("\n", " ").strip()
        ok = http_status == 200 and finished

        return RequestResult(
            index=idx,
            query=query,
            request_started_at=request_started_at,
            request_ended_at=now_iso(),
            http_status=http_status,
            ok=ok,
            finished=finished,
            total_ms=round(total_ms, 3),
            ttft_ms=None if ttft_ms is None else round(ttft_ms, 3),
            stream_lines=stream_lines,
            response_chars=response_chars,
            answer_preview=answer_preview,
            error_type=None,
            error_message=None,
        )
    except asyncio.TimeoutError as e:
        return RequestResult(
            index=idx,
            query=query,
            request_started_at=request_started_at,
            request_ended_at=now_iso(),
            http_status=http_status,
            ok=False,
            finished=False,
            total_ms=round((time.perf_counter() - t0) * 1000, 3),
            ttft_ms=None if first_chunk_ts is None else round((first_chunk_ts - t0) * 1000, 3),
            stream_lines=stream_lines,
            response_chars=response_chars,
            answer_preview="",
            error_type=type(e).__name__,
            error_message=str(e),
        )
    except Exception as e:
        return RequestResult(
            index=idx,
            query=query,
            request_started_at=request_started_at,
            request_ended_at=now_iso(),
            http_status=http_status,
            ok=False,
            finished=False,
            total_ms=round((time.perf_counter() - t0) * 1000, 3),
            ttft_ms=None if first_chunk_ts is None else round((first_chunk_ts - t0) * 1000, 3),
            stream_lines=stream_lines,
            response_chars=response_chars,
            answer_preview="",
            error_type=type(e).__name__,
            error_message=str(e),
        )


def build_summary(results: list[RequestResult], started_at: str, finished_at: str, elapsed_sec: float) -> dict[str, Any]:
    total = len(results)
    ok_results = [r for r in results if r.ok]
    fail_results = [r for r in results if not r.ok]

    total_ms_ok = [r.total_ms for r in ok_results]
    ttft_ms_ok = [r.ttft_ms for r in ok_results if r.ttft_ms is not None]

    status_counts = Counter(str(r.http_status) if r.http_status is not None else "None" for r in results)
    err_counts = Counter(r.error_type or "" for r in fail_results if r.error_type)

    return {
        "run": {
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_sec": round(elapsed_sec, 3),
            "throughput_rps": round(total / elapsed_sec, 3) if elapsed_sec > 0 else None,
            "total_requests": total,
            "success_requests": len(ok_results),
            "error_requests": len(fail_results),
            "success_rate": round((len(ok_results) / total * 100), 3) if total else 0.0,
            "status_code_counts": dict(status_counts),
            "error_type_counts": dict(err_counts),
        },
        "latency_total_ms": {
            "min": min(total_ms_ok) if total_ms_ok else None,
            "max": max(total_ms_ok) if total_ms_ok else None,
            "avg": round(statistics.mean(total_ms_ok), 3) if total_ms_ok else None,
            "p50": round(percentile(total_ms_ok, 0.50), 3) if total_ms_ok else None,
            "p90": round(percentile(total_ms_ok, 0.90), 3) if total_ms_ok else None,
            "p95": round(percentile(total_ms_ok, 0.95), 3) if total_ms_ok else None,
            "p99": round(percentile(total_ms_ok, 0.99), 3) if total_ms_ok else None,
        },
        "latency_ttft_ms": {
            "min": min(ttft_ms_ok) if ttft_ms_ok else None,
            "max": max(ttft_ms_ok) if ttft_ms_ok else None,
            "avg": round(statistics.mean(ttft_ms_ok), 3) if ttft_ms_ok else None,
            "p50": round(percentile(ttft_ms_ok, 0.50), 3) if ttft_ms_ok else None,
            "p90": round(percentile(ttft_ms_ok, 0.90), 3) if ttft_ms_ok else None,
            "p95": round(percentile(ttft_ms_ok, 0.95), 3) if ttft_ms_ok else None,
            "p99": round(percentile(ttft_ms_ok, 0.99), 3) if ttft_ms_ok else None,
        },
    }


def dump_csv(results: list[RequestResult], out_csv: Path) -> None:
    if not results:
        out_csv.write_text("", encoding="utf-8")
        return

    fields = list(asdict(results[0]).keys())
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))


def dump_summary_text(summary: dict[str, Any], out_txt: Path) -> None:
    run = summary["run"]
    t_total = summary["latency_total_ms"]
    t_ttft = summary["latency_ttft_ms"]

    lines = [
        "HuizhouPowerQAAgent 并发压测摘要",
        "=" * 40,
        f"started_at: {run['started_at']}",
        f"finished_at: {run['finished_at']}",
        f"elapsed_sec: {run['elapsed_sec']}",
        f"throughput_rps: {run['throughput_rps']}",
        f"total_requests: {run['total_requests']}",
        f"success_requests: {run['success_requests']}",
        f"error_requests: {run['error_requests']}",
        f"success_rate: {run['success_rate']}%",
        f"status_code_counts: {json.dumps(run['status_code_counts'], ensure_ascii=False)}",
        f"error_type_counts: {json.dumps(run['error_type_counts'], ensure_ascii=False)}",
        "",
        "total_ms (仅成功请求):",
        json.dumps(t_total, ensure_ascii=False),
        "",
        "ttft_ms (仅成功请求):",
        json.dumps(t_ttft, ensure_ascii=False),
    ]
    out_txt.write_text("\n".join(lines), encoding="utf-8")


async def main_async(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv).expanduser().resolve()
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 文件不存在: {csv_path}")

    queries = read_queries(csv_path, args.query_col, args.limit)
    if not queries:
        raise RuntimeError(f"未读取到有效 query（列: {args.query_col}）")

    token, auth_mode = resolve_token(args)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    out_dir = Path(args.output_dir).expanduser().resolve() / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    started_at = now_iso()
    t0 = time.perf_counter()

    timeout = aiohttp.ClientTimeout(total=args.request_timeout_sec)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    print(f"[INFO] Run ID: {run_id}")
    print(f"[INFO] Queries: {len(queries)}")
    print("[INFO] Dispatch mode: all_at_once (full concurrency)")

    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        tasks = [
            asyncio.create_task(
                run_one(
                    session=session,
                    api_base=args.api_base,
                    agent_id=args.agent_id,
                    agent_config_id=args.agent_config_id,
                    query=q,
                    idx=i,
                    token=token,
                    timeout_sec=args.request_timeout_sec,
                    save_full_answer=args.save_full_answer,
                )
            )
            for i, q in enumerate(queries, 1)
        ]
        results = await asyncio.gather(*tasks)

    elapsed_sec = time.perf_counter() - t0
    finished_at = now_iso()

    summary = build_summary(results, started_at, finished_at, elapsed_sec)

    run_params = {
        "run_id": run_id,
        "api_base": args.api_base,
        "agent_id": args.agent_id,
        "agent_config_id": args.agent_config_id,
        "csv": str(csv_path),
        "query_col": args.query_col,
        "query_count": len(queries),
        "dispatch_mode": "all_at_once",
        "request_timeout_sec": args.request_timeout_sec,
        "auth_mode": auth_mode,
        "save_full_answer": args.save_full_answer,
        "limit": args.limit,
    }

    report_json = {
        "params": run_params,
        "summary": summary,
        "results": [asdict(r) for r in results],
    }

    out_json = out_dir / "report.json"
    out_csv = out_dir / "results.csv"
    out_txt = out_dir / "summary.txt"

    out_json.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
    dump_csv(results, out_csv)
    dump_summary_text(summary, out_txt)

    print("\n[INFO] Benchmark done")
    print(f"[INFO] report.json: {out_json}")
    print(f"[INFO] results.csv: {out_csv}")
    print(f"[INFO] summary.txt: {out_txt}")
    print(f"[INFO] success/total: {summary['run']['success_requests']}/{summary['run']['total_requests']}")
    print(f"[INFO] success_rate: {summary['run']['success_rate']}%")
    print(f"[INFO] throughput_rps: {summary['run']['throughput_rps']}")

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="CSV query 并发压测 HuizhouPowerQAAgent")
    parser.add_argument(
        "--csv",
        default="data/qa_datasets/hz_power_marketing_qa_dataset_20260320.csv",
        help="输入 CSV 路径",
    )
    parser.add_argument("--query-col", default="query", help="CSV 中问题列名")
    parser.add_argument("--api-base", default="http://127.0.0.1:5050", help="API 基础地址")
    parser.add_argument("--agent-id", default="HuizhouPowerQAAgent", help="智能体 ID")
    parser.add_argument("--agent-config-id", type=int, default=9, help="agent_config_id")
    parser.add_argument("--request-timeout-sec", type=int, default=120, help="单请求总超时秒数")
    parser.add_argument(
        "--output-dir",
        default="reports/huizhou_chat_benchmark",
        help="报告输出目录（会自动创建 run_id 子目录）",
    )
    parser.add_argument("--limit", type=int, default=None, help="仅测试前 N 条 query（默认全量）")

    parser.add_argument("--token", default=None, help="可直接传 Bearer Token")
    parser.add_argument("--username", default=None, help="账号登录获取 token（可选）")
    parser.add_argument("--password", default=None, help="账号登录获取 token（可选）")

    parser.add_argument(
        "--save-full-answer",
        action="store_true",
        help="在 report.json 中保存完整 answer（默认只存预览片段）",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
