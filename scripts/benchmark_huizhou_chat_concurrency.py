#!/usr/bin/env python3
"""
Concurrent benchmark for HuizhouPowerQAAgent using the CSV `query` column.

Features:
1) Full fan-out by default (all requests dispatched at once)
2) Per-request metrics (HTTP status, TTFT, total latency, stream lines, output tokens, errors)
3) Detailed outputs: JSON (full), CSV (rows), TXT (summary)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import html
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
    output_tokens: int | None
    output_tokens_per_sec: float | None
    answer_preview: str
    error_type: str | None
    error_message: str | None


class TaskConcurrencyTracker:
    def __init__(self) -> None:
        self._active = 0
        self._peak = 0
        self._lock = asyncio.Lock()

    async def enter(self) -> None:
        async with self._lock:
            self._active += 1
            if self._active > self._peak:
                self._peak = self._active

    async def exit(self) -> None:
        async with self._lock:
            self._active = max(0, self._active - 1)

    @property
    def peak(self) -> int:
        return self._peak


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


def parse_int_token(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float):
        return int(value) if value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            num = float(text)
        except ValueError:
            return None
        return int(num) if num >= 0 else None
    return None


def extract_output_tokens_from_stream_obj(obj: dict[str, Any]) -> int | None:
    def usage_candidates() -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        if isinstance(obj, dict):
            candidates.append(obj)
        if isinstance(obj.get("usage_metadata"), dict):
            candidates.append(obj["usage_metadata"])

        msg = obj.get("msg")
        if isinstance(msg, dict):
            candidates.append(msg)
            if isinstance(msg.get("usage_metadata"), dict):
                candidates.append(msg["usage_metadata"])
            if isinstance(msg.get("response_metadata"), dict):
                response_metadata = msg["response_metadata"]
                candidates.append(response_metadata)
                if isinstance(response_metadata.get("token_usage"), dict):
                    candidates.append(response_metadata["token_usage"])
                if isinstance(response_metadata.get("usage"), dict):
                    candidates.append(response_metadata["usage"])
        return candidates

    total_fallback: int | None = None
    for candidate in usage_candidates():
        for key in ("output_tokens", "completion_tokens", "generated_tokens", "answer_tokens"):
            value = parse_int_token(candidate.get(key))
            if value is not None:
                return value
        if total_fallback is None:
            total_fallback = parse_int_token(candidate.get("total_tokens"))
    return total_fallback


def resolve_effective_output_tokens(output_tokens: int | None, response_chars: int, stream_lines: int) -> int | None:
    if output_tokens is not None:
        return output_tokens
    if response_chars > 0:
        return response_chars
    if stream_lines > 0:
        return stream_lines
    return None


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
        raise RuntimeError(f"Login succeeded but no access_token returned: {body}")
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
        raise RuntimeError(f"Failed to generate token via docker compose: {proc.stderr.strip()}")
    lines = [x.strip() for x in (proc.stdout or "").splitlines() if x.strip()]
    if not lines:
        raise RuntimeError("Failed to generate token via docker compose: empty output")
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
            print(f"[WARN] Username/password token login failed; fallback to docker compose token: {e}")

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
    retry_count = 0
    while True:
        first_chunk_ts: float | None = None
        http_status: int | None = None
        stream_lines = 0
        response_chars = 0
        output_tokens: int | None = None
        finished = False
        answer_parts: list[str] = []

        try:
            async with session.post(url, json=payload) as resp:
                http_status = resp.status
                if http_status == 429:
                    retry_count += 1
                    retry_after = resp.headers.get("Retry-After")
                    retry_after_sec = 1.0
                    if retry_after:
                        try:
                            retry_after_sec = max(float(retry_after), 0.0)
                        except ValueError:
                            pass
                    print(
                        f"[WARN] Request #{idx} hit 429, retrying forever "
                        f"(retry_count={retry_count}, sleep={retry_after_sec}s)"
                    )
                    await asyncio.sleep(retry_after_sec)
                    continue

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

                        parsed_output_tokens = extract_output_tokens_from_stream_obj(obj)
                        if parsed_output_tokens is not None:
                            output_tokens = max(output_tokens or 0, parsed_output_tokens)

                        part = obj.get("response")
                        if isinstance(part, str) and part:
                            response_chars += len(part)
                            if save_full_answer:
                                answer_parts.append(part)
                            elif len("".join(answer_parts)) < 600:
                                answer_parts.append(part)

                        if obj.get("status") == "finished":
                            finished = True

                # Handle the final buffered line without trailing newline
                tail = buf.strip()
                if tail:
                    stream_lines += 1
                    try:
                        obj = json.loads(tail)
                        parsed_output_tokens = extract_output_tokens_from_stream_obj(obj)
                        if parsed_output_tokens is not None:
                            output_tokens = max(output_tokens or 0, parsed_output_tokens)
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
            effective_output_tokens = resolve_effective_output_tokens(output_tokens, response_chars, stream_lines)
            output_tokens_per_sec = (
                (effective_output_tokens / (total_ms / 1000))
                if effective_output_tokens is not None and total_ms > 0
                else None
            )
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
                output_tokens=effective_output_tokens,
                output_tokens_per_sec=None if output_tokens_per_sec is None else round(output_tokens_per_sec, 3),
                answer_preview=answer_preview,
                error_type=None,
                error_message=None,
            )
        except asyncio.TimeoutError as e:
            effective_output_tokens = resolve_effective_output_tokens(output_tokens, response_chars, stream_lines)
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
                output_tokens=effective_output_tokens,
                output_tokens_per_sec=(
                    None
                    if effective_output_tokens is None
                    else round(effective_output_tokens / max((time.perf_counter() - t0), 1e-9), 3)
                ),
                answer_preview="",
                error_type=type(e).__name__,
                error_message=str(e),
            )
        except Exception as e:
            effective_output_tokens = resolve_effective_output_tokens(output_tokens, response_chars, stream_lines)
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
                output_tokens=effective_output_tokens,
                output_tokens_per_sec=(
                    None
                    if effective_output_tokens is None
                    else round(effective_output_tokens / max((time.perf_counter() - t0), 1e-9), 3)
                ),
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
    output_tokens_ok = [r.output_tokens for r in ok_results if r.output_tokens is not None]

    status_counts = Counter(str(r.http_status) if r.http_status is not None else "None" for r in results)
    err_counts = Counter(r.error_type or "" for r in fail_results if r.error_type)

    return {
        "run": {
            "started_at": started_at,
            "finished_at": finished_at,
            "elapsed_sec": round(elapsed_sec, 3),
            "throughput_rps": round(total / elapsed_sec, 3) if elapsed_sec > 0 else None,
            "output_tokens_total": sum(output_tokens_ok) if output_tokens_ok else None,
            "throughput_tokens_per_sec": round(sum(output_tokens_ok) / elapsed_sec, 3)
            if elapsed_sec > 0 and output_tokens_ok
            else None,
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
        "HuizhouPowerQAAgent Concurrent Benchmark Summary",
        "=" * 40,
        f"started_at: {run['started_at']}",
        f"finished_at: {run['finished_at']}",
        f"elapsed_sec: {run['elapsed_sec']}",
        f"throughput_rps: {run['throughput_rps']}",
        f"output_tokens_total: {run.get('output_tokens_total')}",
        f"throughput_tokens_per_sec: {run.get('throughput_tokens_per_sec')}",
        f"total_requests: {run['total_requests']}",
        f"success_requests: {run['success_requests']}",
        f"error_requests: {run['error_requests']}",
        f"success_rate: {run['success_rate']}%",
        f"peak_task_concurrency: {run.get('peak_task_concurrency')}",
        f"status_code_counts: {json.dumps(run['status_code_counts'], ensure_ascii=False)}",
        f"error_type_counts: {json.dumps(run['error_type_counts'], ensure_ascii=False)}",
        "",
        "total_ms (successful requests only):",
        json.dumps(t_total, ensure_ascii=False),
        "",
        "ttft_ms (successful requests only):",
        json.dumps(t_ttft, ensure_ascii=False),
    ]
    out_txt.write_text("\n".join(lines), encoding="utf-8")


def parse_iso_datetime(dt: str) -> datetime | None:
    try:
        return datetime.fromisoformat(dt)
    except Exception:
        return None


def dump_request_race_track_svg(results: list[RequestResult], out_svg: Path) -> None:
    rows: list[tuple[RequestResult, datetime, datetime]] = []
    for result in sorted(results, key=lambda x: x.index):
        start_dt = parse_iso_datetime(result.request_started_at)
        end_dt = parse_iso_datetime(result.request_ended_at)
        if start_dt is None or end_dt is None:
            continue
        if end_dt < start_dt:
            end_dt = start_dt
        rows.append((result, start_dt, end_dt))

    if not rows:
        out_svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="800" height="120">'
            '<text x="20" y="60" font-family="Arial,sans-serif" font-size="16">'
            "No valid request timestamps to draw race track."
            "</text></svg>",
            encoding="utf-8",
        )
        return

    min_start = min(start for _, start, _ in rows)
    max_end = max(end for _, _, end in rows)
    total_ms = max((max_end - min_start).total_seconds() * 1000, 1.0)

    label_w = 260
    plot_w = 1100
    top = 72
    row_h = 22
    row_gap = 10
    bottom = 70
    right = 50
    plot_h = len(rows) * (row_h + row_gap) - row_gap
    width = label_w + plot_w + right
    height = top + plot_h + bottom

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        "<style>",
        "text { font-family: Arial, sans-serif; fill: #1f1f1f; }",
        ".title { font-size: 20px; font-weight: 700; }",
        ".axis-label { font-size: 12px; fill: #666; }",
        ".row-label { font-size: 12px; fill: #444; }",
        ".value-label { font-size: 11px; fill: #333; }",
        "</style>",
        '<rect x="0" y="0" width="100%" height="100%" fill="#ffffff"/>',
        f'<text class="title" x="{label_w}" y="34">Request Race Track</text>',
        f'<text class="axis-label" x="{label_w}" y="54">Time span: {total_ms:.1f} ms</text>',
    ]

    # time grid
    tick_count = 10
    for tick in range(tick_count + 1):
        ratio = tick / tick_count
        x = label_w + ratio * plot_w
        ms = total_ms * ratio
        parts.append(f'<line x1="{x:.2f}" y1="{top-8}" x2="{x:.2f}" y2="{top + plot_h}" stroke="#f0f0f0"/>')
        parts.append(
            f'<text class="axis-label" x="{x:.2f}" y="{top + plot_h + 20}" text-anchor="middle">'
            f"{ms/1000:.2f}s</text>"
        )

    # rows and bars
    for i, (result, start_dt, end_dt) in enumerate(rows):
        y = top + i * (row_h + row_gap)
        start_offset_ms = max((start_dt - min_start).total_seconds() * 1000, 0.0)
        duration_ms = max((end_dt - start_dt).total_seconds() * 1000, 0.0)
        bar_x = label_w + (start_offset_ms / total_ms) * plot_w
        bar_w = max((duration_ms / total_ms) * plot_w, 2.0)
        status_color = "#52c41a" if result.ok else "#ff4d4f"
        query_text = result.query.strip().replace("\n", " ")
        if len(query_text) > 26:
            query_text = query_text[:26] + "..."
        row_label = f"#{result.index} {query_text}"

        parts.append(
            f'<text class="row-label" x="{label_w - 8}" y="{y + row_h - 6}" text-anchor="end">'
            f"{html.escape(row_label)}</text>"
        )
        parts.append(
            f'<rect x="{bar_x:.2f}" y="{y}" width="{bar_w:.2f}" height="{row_h}" '
            f'rx="4" ry="4" fill="{status_color}" opacity="0.9"/>'
        )
        parts.append(
            f'<text class="value-label" x="{bar_x + bar_w + 6:.2f}" y="{y + row_h - 6}">'
            f"{duration_ms:.1f} ms</text>"
        )

    parts.append("</svg>")
    out_svg.write_text("\n".join(parts), encoding="utf-8")


async def run_benchmark_round(
    *,
    session: aiohttp.ClientSession,
    args: argparse.Namespace,
    queries: list[str],
    token: str,
    concurrency_limit: int,
) -> tuple[list[RequestResult], dict[str, Any]]:
    started_at = now_iso()
    t0 = time.perf_counter()

    bounded_concurrency = max(1, min(concurrency_limit, len(queries)))
    semaphore = asyncio.Semaphore(bounded_concurrency)
    concurrency_tracker = TaskConcurrencyTracker()

    async def run_one_with_tracking(query: str, idx: int) -> RequestResult:
        async with semaphore:
            await concurrency_tracker.enter()
            try:
                return await run_one(
                    session=session,
                    api_base=args.api_base,
                    agent_id=args.agent_id,
                    agent_config_id=args.agent_config_id,
                    query=query,
                    idx=idx,
                    token=token,
                    timeout_sec=args.request_timeout_sec,
                    save_full_answer=args.save_full_answer,
                )
            finally:
                await concurrency_tracker.exit()

    tasks = [asyncio.create_task(run_one_with_tracking(query=q, idx=i)) for i, q in enumerate(queries, 1)]
    results = await asyncio.gather(*tasks)

    elapsed_sec = time.perf_counter() - t0
    finished_at = now_iso()
    summary = build_summary(results, started_at, finished_at, elapsed_sec)
    summary["run"]["peak_task_concurrency"] = concurrency_tracker.peak
    summary["run"]["target_concurrency"] = bounded_concurrency
    return results, summary


def build_sweep_concurrency_values(max_concurrency: int, step: int) -> list[int]:
    upper = max(1, max_concurrency)
    stride = max(1, step)
    values = list(range(1, upper + 1, stride))
    if values[-1] != upper:
        values.append(upper)
    return values


def build_sweep_row(summary: dict[str, Any]) -> dict[str, Any]:
    run = summary["run"]
    latency_total = summary["latency_total_ms"]
    latency_ttft = summary["latency_ttft_ms"]
    return {
        "concurrency": run.get("target_concurrency"),
        "success_rate": run.get("success_rate"),
        "throughput_rps": run.get("throughput_rps"),
        "throughput_tokens_per_sec": run.get("throughput_tokens_per_sec"),
        "latency_avg_ms": latency_total.get("avg"),
        "latency_p95_ms": latency_total.get("p95"),
        "latency_p99_ms": latency_total.get("p99"),
        "ttft_avg_ms": latency_ttft.get("avg"),
    }


def pick_best_latency_point(sweep_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [row for row in sweep_rows if row.get("latency_p95_ms") is not None]
    if not candidates:
        return None
    candidates.sort(
        key=lambda row: (
            float(row["latency_p95_ms"]),
            float(row["latency_avg_ms"]) if row.get("latency_avg_ms") is not None else float("inf"),
            -float(row["throughput_rps"]) if row.get("throughput_rps") is not None else float("inf"),
            int(row["concurrency"] or 0),
        )
    )
    return candidates[0]


def dump_concurrency_sweep_csv(sweep_rows: list[dict[str, Any]], out_csv: Path) -> None:
    if not sweep_rows:
        out_csv.write_text("", encoding="utf-8")
        return
    fields = list(sweep_rows[0].keys())
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in sweep_rows:
            writer.writerow(row)


def dump_concurrency_latency_curve_svg(
    sweep_rows: list[dict[str, Any]],
    out_svg: Path,
    best_point: dict[str, Any] | None,
) -> None:
    rows = [row for row in sweep_rows if isinstance(row.get("concurrency"), int)]
    if not rows:
        out_svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="140">'
            '<text x="20" y="70" font-family="Arial,sans-serif" font-size="16">'
            "No sweep data to draw concurrency-latency curve."
            "</text></svg>",
            encoding="utf-8",
        )
        return

    metrics = [
        ("latency_avg_ms", "avg", "#1677ff"),
        ("latency_p95_ms", "p95", "#fa8c16"),
        ("latency_p99_ms", "p99", "#f5222d"),
    ]
    metric_points: dict[str, list[tuple[int, float]]] = {}
    all_latency_values: list[float] = []
    for key, _, _ in metrics:
        pts: list[tuple[int, float]] = []
        for row in rows:
            value = row.get(key)
            if value is None:
                continue
            pts.append((int(row["concurrency"]), float(value)))
            all_latency_values.append(float(value))
        metric_points[key] = pts

    if not all_latency_values:
        out_svg.write_text(
            '<svg xmlns="http://www.w3.org/2000/svg" width="900" height="140">'
            '<text x="20" y="70" font-family="Arial,sans-serif" font-size="16">'
            "Sweep completed but no latency values available."
            "</text></svg>",
            encoding="utf-8",
        )
        return

    min_concurrency = min(int(row["concurrency"]) for row in rows)
    max_concurrency = max(int(row["concurrency"]) for row in rows)
    max_latency = max(max(all_latency_values), 1.0)

    left = 80
    right = 40
    top = 80
    bottom = 80
    plot_w = 980
    plot_h = 430
    width = left + plot_w + right
    height = top + plot_h + bottom

    def x_for(concurrency: int) -> float:
        if max_concurrency == min_concurrency:
            return left + plot_w / 2
        return left + (concurrency - min_concurrency) / (max_concurrency - min_concurrency) * plot_w

    def y_for(latency_ms: float) -> float:
        return top + (1 - latency_ms / max_latency) * plot_h

    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">',
        "<style>",
        "text { font-family: Arial, sans-serif; fill: #222; }",
        ".title { font-size: 22px; font-weight: 700; }",
        ".sub { font-size: 13px; fill: #666; }",
        ".axis { font-size: 12px; fill: #666; }",
        ".legend { font-size: 12px; }",
        "</style>",
        '<rect x="0" y="0" width="100%" height="100%" fill="#fff"/>',
        f'<text class="title" x="{left}" y="36">Concurrency vs Latency</text>',
        f'<text class="sub" x="{left}" y="58">Latency unit: ms, lower is better</text>',
    ]

    y_ticks = 6
    for i in range(y_ticks + 1):
        ratio = i / y_ticks
        value = max_latency * (1 - ratio)
        y = top + ratio * plot_h
        parts.append(f'<line x1="{left}" y1="{y:.2f}" x2="{left + plot_w}" y2="{y:.2f}" stroke="#f0f0f0"/>')
        parts.append(
            f'<text class="axis" x="{left - 8}" y="{y + 4:.2f}" text-anchor="end">{value:.1f}</text>'
        )

    for row in rows:
        c = int(row["concurrency"])
        x = x_for(c)
        parts.append(f'<line x1="{x:.2f}" y1="{top}" x2="{x:.2f}" y2="{top + plot_h}" stroke="#fafafa"/>')
        parts.append(
            f'<text class="axis" x="{x:.2f}" y="{top + plot_h + 22}" text-anchor="middle">{c}</text>'
        )

    parts.append(
        f'<text class="axis" x="{left + plot_w / 2:.2f}" y="{height - 24}" text-anchor="middle">concurrency</text>'
    )
    parts.append(
        f'<text class="axis" transform="translate(24,{top + plot_h / 2:.2f}) rotate(-90)" text-anchor="middle">latency (ms)</text>'
    )

    legend_x = left
    for key, label, color in metrics:
        parts.append(f'<rect x="{legend_x}" y="66" width="16" height="4" fill="{color}" rx="2" ry="2"/>')
        parts.append(f'<text class="legend" x="{legend_x + 22}" y="72">{label}</text>')
        legend_x += 90

    for key, _, color in metrics:
        pts = metric_points[key]
        if not pts:
            continue
        point_str = " ".join(f"{x_for(c):.2f},{y_for(v):.2f}" for c, v in pts)
        parts.append(f'<polyline fill="none" stroke="{color}" stroke-width="2.4" points="{point_str}"/>')
        for c, v in pts:
            parts.append(
                f'<circle cx="{x_for(c):.2f}" cy="{y_for(v):.2f}" r="3.2" fill="#fff" stroke="{color}" stroke-width="1.8"/>'
            )

    if best_point and best_point.get("concurrency") is not None and best_point.get("latency_p95_ms") is not None:
        best_c = int(best_point["concurrency"])
        best_p95 = float(best_point["latency_p95_ms"])
        bx = x_for(best_c)
        by = y_for(best_p95)
        parts.append(f'<circle cx="{bx:.2f}" cy="{by:.2f}" r="6" fill="none" stroke="#13c2c2" stroke-width="2.2"/>')
        parts.append(
            f'<text class="sub" x="{bx + 10:.2f}" y="{by - 10:.2f}">best p95: c={best_c}, {best_p95:.1f}ms</text>'
        )

    parts.append("</svg>")
    out_svg.write_text("\n".join(parts), encoding="utf-8")


def dump_markdown_report(
    summary: dict[str, Any],
    out_md: Path,
    race_track_svg_name: str,
    sweep_rows: list[dict[str, Any]] | None = None,
    sweep_curve_svg_name: str | None = None,
    sweep_best_point: dict[str, Any] | None = None,
) -> None:
    run = summary["run"]
    latency_total = summary["latency_total_ms"]
    latency_ttft = summary["latency_ttft_ms"]

    lines = [
        "# HuizhouPowerQAAgent 并发压测报告",
        "",
        "## 运行概览",
        "",
        "| 指标 | 值 |",
        "|---|---|",
        f"| started_at | {run['started_at']} |",
        f"| finished_at | {run['finished_at']} |",
        f"| elapsed_sec | {run['elapsed_sec']} |",
        f"| throughput_rps | {run['throughput_rps']} |",
        f"| output_tokens_total | {run.get('output_tokens_total')} |",
        f"| throughput_tokens_per_sec | {run.get('throughput_tokens_per_sec')} |",
        f"| total_requests | {run['total_requests']} |",
        f"| success_requests | {run['success_requests']} |",
        f"| error_requests | {run['error_requests']} |",
        f"| success_rate | {run['success_rate']}% |",
        f"| peak_task_concurrency | {run.get('peak_task_concurrency')} |",
        "",
        "## 请求赛道图",
        "",
        f"![请求赛道图]({race_track_svg_name})",
        "",
        "说明：图中的横轴时间来自每个请求的 `request_started_at` 和 `request_ended_at`。",
        "",
        "## 延迟统计（仅成功请求）",
        "",
        f"- total_ms: `{json.dumps(latency_total, ensure_ascii=False)}`",
        f"- ttft_ms: `{json.dumps(latency_ttft, ensure_ascii=False)}`",
        "",
        "## 其他统计",
        "",
        f"- status_code_counts: `{json.dumps(run['status_code_counts'], ensure_ascii=False)}`",
        f"- error_type_counts: `{json.dumps(run['error_type_counts'], ensure_ascii=False)}`",
    ]

    if sweep_rows:
        lines.extend(
            [
                "",
                "## 并发 vs 延迟曲线（阶梯压测）",
                "",
                f"![并发-延迟曲线]({sweep_curve_svg_name})" if sweep_curve_svg_name else "",
                "",
            ]
        )
        if sweep_best_point:
            lines.append(
                f"- 最优 p95 点: concurrency={sweep_best_point.get('concurrency')}, "
                f"p95={sweep_best_point.get('latency_p95_ms')}ms"
            )
            lines.append("")
        lines.extend(
            [
                "| concurrency | avg_ms | p95_ms | p99_ms | ttft_avg_ms | throughput_rps | token/s | success_rate |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in sweep_rows:
            lines.append(
                f"| {row.get('concurrency')} | {row.get('latency_avg_ms')} | {row.get('latency_p95_ms')} | "
                f"{row.get('latency_p99_ms')} | {row.get('ttft_avg_ms')} | {row.get('throughput_rps')} | "
                f"{row.get('throughput_tokens_per_sec')} | {row.get('success_rate')}% |"
            )
    out_md.write_text("\n".join(lines), encoding="utf-8")


async def main_async(args: argparse.Namespace) -> int:
    csv_path = Path(args.csv).expanduser().resolve()
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    queries = read_queries(csv_path, args.query_col, args.limit)
    if not queries:
        raise RuntimeError(f"No valid queries found (column: {args.query_col})")

    token, auth_mode = resolve_token(args)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    out_dir = Path(args.output_dir).expanduser().resolve() / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    timeout = aiohttp.ClientTimeout(total=args.request_timeout_sec)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    print(f"[INFO] Run ID: {run_id}")
    print(f"[INFO] Queries: {len(queries)}")
    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
        sweep_rows: list[dict[str, Any]] = []
        sweep_best_point: dict[str, Any] | None = None
        if args.sweep_concurrency:
            print("[INFO] Dispatch mode: sweep_only")
            requested_sweep_max = args.sweep_max_concurrency if args.sweep_max_concurrency is not None else len(queries)
            sweep_max_concurrency = max(1, min(len(queries), requested_sweep_max))
            sweep_values = build_sweep_concurrency_values(sweep_max_concurrency, args.sweep_step)
            print(
                f"[INFO] Sweep mode enabled: concurrency from {sweep_values[0]} to {sweep_values[-1]}, "
                f"step={max(args.sweep_step, 1)}, rounds={len(sweep_values)}"
            )
            results: list[RequestResult] = []
            summary: dict[str, Any] | None = None
            for concurrency in sweep_values:
                round_queries = queries[:concurrency]
                print(
                    f"[INFO] Sweep round start: concurrency={concurrency}, "
                    f"queries_in_round={len(round_queries)}"
                )
                sweep_results, sweep_summary = await run_benchmark_round(
                    session=session,
                    args=args,
                    queries=round_queries,
                    token=token,
                    concurrency_limit=concurrency,
                )
                row = build_sweep_row(sweep_summary)
                sweep_rows.append(row)
                results = sweep_results
                summary = sweep_summary
                print(
                    f"[INFO] Sweep round done: concurrency={concurrency}, "
                    f"p95={row.get('latency_p95_ms')}ms, throughput_rps={row.get('throughput_rps')}"
                )
            if summary is None:
                raise RuntimeError("Sweep mode produced no summary")
            sweep_best_point = pick_best_latency_point(sweep_rows)
        else:
            print("[INFO] Dispatch mode: all_at_once (full concurrency)")
            results, summary = await run_benchmark_round(
                session=session,
                args=args,
                queries=queries,
                token=token,
                concurrency_limit=len(queries),
            )
            sweep_max_concurrency = None
            sweep_values = []

    run_params = {
        "run_id": run_id,
        "api_base": args.api_base,
        "agent_id": args.agent_id,
        "agent_config_id": args.agent_config_id,
        "csv": str(csv_path),
        "query_col": args.query_col,
        "query_count": len(queries),
        "dispatch_mode": "sweep_only" if args.sweep_concurrency else "all_at_once",
        "request_timeout_sec": args.request_timeout_sec,
        "auth_mode": auth_mode,
        "save_full_answer": args.save_full_answer,
        "limit": args.limit,
        "peak_task_concurrency": summary["run"]["peak_task_concurrency"],
        "sweep_concurrency": args.sweep_concurrency,
        "sweep_max_concurrency": sweep_max_concurrency,
        "sweep_step": max(args.sweep_step, 1),
    }

    report_json = {
        "params": run_params,
        "summary": summary,
        "results": [asdict(r) for r in results],
    }
    if args.sweep_concurrency:
        report_json["sweep"] = {
            "concurrency_values": sweep_values,
            "rows": sweep_rows,
            "best_point": sweep_best_point,
        }

    out_json = out_dir / "report.json"
    out_csv = out_dir / "results.csv"
    out_txt = out_dir / "summary.txt"
    out_svg = out_dir / "request_race_track.svg"
    out_sweep_csv = out_dir / "concurrency_sweep.csv"
    out_sweep_svg = out_dir / "concurrency_latency_curve.svg"
    out_md = out_dir / "report.md"

    dump_request_race_track_svg(results, out_svg)
    if args.sweep_concurrency:
        dump_concurrency_sweep_csv(sweep_rows, out_sweep_csv)
        dump_concurrency_latency_curve_svg(sweep_rows, out_sweep_svg, sweep_best_point)
    dump_markdown_report(
        summary,
        out_md,
        out_svg.name,
        sweep_rows=sweep_rows if args.sweep_concurrency else None,
        sweep_curve_svg_name=out_sweep_svg.name if args.sweep_concurrency else None,
        sweep_best_point=sweep_best_point if args.sweep_concurrency else None,
    )

    report_json["artifacts"] = {
        "request_race_track_svg": out_svg.name,
        "report_markdown": out_md.name,
    }
    if args.sweep_concurrency:
        report_json["artifacts"]["concurrency_sweep_csv"] = out_sweep_csv.name
        report_json["artifacts"]["concurrency_latency_curve_svg"] = out_sweep_svg.name

    out_json.write_text(json.dumps(report_json, ensure_ascii=False, indent=2), encoding="utf-8")
    dump_csv(results, out_csv)
    dump_summary_text(summary, out_txt)

    print("\n[INFO] Benchmark done")
    print(f"[INFO] report.json: {out_json}")
    print(f"[INFO] results.csv: {out_csv}")
    print(f"[INFO] summary.txt: {out_txt}")
    print(f"[INFO] request_race_track.svg: {out_svg}")
    if args.sweep_concurrency:
        print(f"[INFO] concurrency_sweep.csv: {out_sweep_csv}")
        print(f"[INFO] concurrency_latency_curve.svg: {out_sweep_svg}")
    print(f"[INFO] report.md: {out_md}")
    print(f"[INFO] success/total: {summary['run']['success_requests']}/{summary['run']['total_requests']}")
    print(f"[INFO] success_rate: {summary['run']['success_rate']}%")
    print(f"[INFO] throughput_rps: {summary['run']['throughput_rps']}")
    print(f"[INFO] throughput_tokens_per_sec: {summary['run'].get('throughput_tokens_per_sec')}")
    print(f"[INFO] peak_task_concurrency: {summary['run']['peak_task_concurrency']}")
    print("[INFO] summary:")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Concurrent benchmark for HuizhouPowerQAAgent using CSV queries")
    parser.add_argument(
        "--csv",
        default="data/qa_datasets/hz_power_marketing_qa_dataset_20260320.csv",
        help="Input CSV path",
    )
    parser.add_argument("--query-col", default="query", help="Query column name in CSV")
    parser.add_argument("--api-base", default="http://127.0.0.1:5050", help="API base URL")
    parser.add_argument("--agent-id", default="HuizhouPowerQAAgent", help="Agent ID")
    parser.add_argument("--agent-config-id", type=int, default=9, help="agent_config_id")
    parser.add_argument("--request-timeout-sec", type=int, default=600, help="Per-request total timeout in seconds")
    parser.add_argument(
        "--output-dir",
        default="reports/huizhou_chat_benchmark",
        help="Output directory (run_id subfolder will be created)",
    )
    parser.add_argument("--limit", type=int, default=None, help="Use first N queries only (default: all)")
    parser.add_argument(
        "--sweep-concurrency",
        "--swep",
        action="store_true",
        dest="sweep_concurrency",
        help="Run step-wise concurrency sweep (1..N) and generate concurrency-latency curve",
    )
    parser.add_argument(
        "--sweep-max-concurrency",
        type=int,
        default=None,
        help="Maximum concurrency for sweep (default: query count)",
    )
    parser.add_argument(
        "--sweep-step",
        type=int,
        default=1,
        help="Sweep step size between consecutive concurrency levels",
    )

    parser.add_argument("--token", default=None, help="Provide Bearer token directly")
    parser.add_argument("--username", default=None, help="Username for login token (optional)")
    parser.add_argument("--password", default=None, help="Password for login token (optional)")

    parser.add_argument(
        "--save-full-answer",
        action="store_true",
        help="Store full answer in report.json (default stores preview only)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
