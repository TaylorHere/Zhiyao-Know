#!/usr/bin/env python3
"""
Check whether the hidden knowledge base and bound agent exist and work correctly.

Default checks:
1) Hidden KB exists and visibility=agent_only
2) HuizhouPowerQAAgent is bound only to this hidden KB
3) HuizhouPowerQAAgent default config contains only this hidden KB
4) One chat call returns finished with non-empty answer
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

def run_cmd(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, check=False, capture_output=True, text=True, cwd=str(REPO_ROOT))
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        raise RuntimeError(
            f"command failed (exit={proc.returncode}): {' '.join(cmd)}\nstdout:\n{stdout}\nstderr:\n{stderr}"
        )
    return (proc.stdout or "").strip()


def psql_query(sql: str) -> str:
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "postgres",
        "-d",
        "yuxi_know",
        "-At",
        "-F",
        "|",
        "-c",
        sql,
    ]
    return run_cmd(cmd)


def check_hidden_kb(kb_name: str) -> tuple[bool, str]:
    out = psql_query(
        f"select db_id,name,visibility from knowledge_bases where name='{kb_name}' limit 1;"
    )
    if not out:
        return False, "Hidden KB not found"
    db_id, name, visibility = out.split("|", 2)
    if visibility != "agent_only":
        return False, f"Unexpected hidden KB visibility: {visibility}"
    return True, db_id


def check_binding(agent_id: str, expected_kb_id: str) -> tuple[bool, str]:
    out = psql_query(
        f"select kb_id from kb_agent_bindings where agent_id='{agent_id}' order by kb_id;"
    )
    kb_ids = [x.strip() for x in out.splitlines() if x.strip()]
    if kb_ids != [expected_kb_id]:
        return False, f"Unexpected bindings: {kb_ids}"
    return True, "OK"


def check_default_config(agent_id: str, kb_name: str) -> tuple[bool, str]:
    out = psql_query(
        "select id,is_default,coalesce(config_json->'context'->'knowledges','[]'::json)::text "
        f"from agent_configs where agent_id='{agent_id}' order by id;"
    )
    if not out:
        return False, "Agent config not found"
    lines = [x for x in out.splitlines() if x.strip()]
    default_line = None
    for line in lines:
        _, is_default, _ = line.split("|", 2)
        if is_default == "t":
            default_line = line
            break
    if default_line is None:
        return False, "Default config not found"
    _, _, knowledges_text = default_line.split("|", 2)
    knowledges = json.loads(knowledges_text)
    if knowledges != [kb_name]:
        return False, f"Unexpected knowledges in default config: {knowledges}"
    return True, "OK"


def issue_token() -> str:
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
    out = run_cmd(cmd)
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    if not lines:
        raise RuntimeError("Failed to issue token")
    return lines[-1]


def chat_smoke_test(api_base: str, agent_id: str, agent_config_id: int, query: str) -> tuple[bool, str]:
    token = issue_token()
    payload = {
        "query": query,
        "config": {"agent_config_id": agent_config_id},
        "meta": {},
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base}/api/chat/agent/{agent_id}",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
    except urllib.error.URLError as e:
        return False, f"Chat request failed: {e}"
    except TimeoutError:
        return False, "Chat request timeout (120s)"
    except Exception as e:
        return False, f"Chat request exception: {e}"

    finished = False
    answer = ""
    for ln in body.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            obj = json.loads(ln)
        except Exception:
            continue
        if obj.get("status") == "finished":
            finished = True
        part = obj.get("response")
        if isinstance(part, str):
            answer += part

    if not finished:
        return False, "Chat did not finish (missing finished status)"
    if not answer.strip():
        return False, "Chat answer is empty"
    return True, answer[:120]


def auto_fix_hidden_setup() -> tuple[bool, str]:
    """
    Auto-fix hidden KB and binding by calling:
    FirstRunSeedService.seed_hidden_huizhou_kb(operator_id=1, department_id=1)
    """
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        (
            "import asyncio; "
            "from src.services.first_run_seed_service import FirstRunSeedService; "
            "r=asyncio.run(FirstRunSeedService.seed_hidden_huizhou_kb(operator_id=1, department_id=1)); "
            "print({'kb_id':r.kb_id,'kb_name':r.kb_name,'agent_id':r.agent_id,'imported':r.imported,'msg':r.message})"
        ),
    ]
    try:
        out = run_cmd(cmd)
        return True, out
    except Exception as e:
        return False, f"Auto-fix execution failed: {e}"


@dataclass
class CheckContext:
    kb_name: str
    agent_id: str
    agent_config_id: int
    api_base: str
    query: str


def run_all_checks(ctx: CheckContext) -> tuple[list[tuple[str, bool, str]], bool]:
    checks: list[tuple[str, bool, str]] = []
    ok, kb_result = check_hidden_kb(ctx.kb_name)
    checks.append(("Hidden KB exists and is agent_only", ok, kb_result))
    if not ok:
        return checks, False
    kb_id = kb_result

    ok, detail = check_binding(ctx.agent_id, kb_id)
    checks.append(("Agent bound only to hidden KB", ok, detail))

    ok2, detail2 = check_default_config(ctx.agent_id, ctx.kb_name)
    checks.append(("Default config points only to hidden KB", ok2, detail2))

    ok3, detail3 = chat_smoke_test(ctx.api_base, ctx.agent_id, ctx.agent_config_id, ctx.query)
    checks.append(("Agent chat is available", ok3, detail3))

    all_ok = all(passed for _, passed, _ in checks)
    return checks, all_ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Health check for hidden KB and bound agent")
    parser.add_argument("--kb-name", default="荆州营销部问答隐藏知识库")
    parser.add_argument("--agent-id", default="HuizhouPowerQAAgent")
    parser.add_argument("--agent-config-id", type=int, default=9)
    parser.add_argument("--api-base", default="http://127.0.0.1:5050")
    parser.add_argument("--query", default="How are legacy and incremental projects distinguished in NEV feed-in tariff reform?")
    parser.add_argument(
        "--auto-fix-on-fail",
        action="store_true",
        help="Run auto-fix when check fails, then re-check",
    )
    args = parser.parse_args()

    ctx = CheckContext(
        kb_name=args.kb_name,
        agent_id=args.agent_id,
        agent_config_id=args.agent_config_id,
        api_base=args.api_base,
        query=args.query,
    )
    checks, all_ok = run_all_checks(ctx)

    for name, passed, detail in checks:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")

    if all_ok:
        print("RESULT: PASS")
        return 0

    if args.auto_fix_on_fail:
        print("Check failed. Starting auto-fix...")
        fixed, fix_msg = auto_fix_hidden_setup()
        print(f"[{'PASS' if fixed else 'FAIL'}] Auto-fix execution: {fix_msg}")
        if not fixed:
            print("RESULT: FAIL")
            return 3

        print("Auto-fix completed. Re-checking...")
        checks2, all_ok2 = run_all_checks(ctx)
        for name, passed, detail in checks2:
            print(f"[{'PASS' if passed else 'FAIL'}] {name}: {detail}")
        if all_ok2:
            print("RESULT: PASS_AFTER_FIX")
            return 0
        print("RESULT: FAIL_AFTER_FIX")
        return 4

    print("RESULT: FAIL")
    return 2


if __name__ == "__main__":
    sys.exit(main())
