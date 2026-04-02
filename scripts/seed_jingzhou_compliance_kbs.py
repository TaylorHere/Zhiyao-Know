#!/usr/bin/env python3
"""
荆州一库两清单：手动种子脚本

作用：
1) 从指定目录读取三份 Excel
2) 同步到项目 saves/jingzhou_compliance_seed/source（容器可见）
3) 调用 api 容器内的 JingzhouComplianceSeedService 执行创建知识库与导入
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from shutil import which
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class ProgressBar:
    def __init__(self) -> None:
        self.percent = 0
        self.stage = "初始化"
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

    def _render(self, percent: int, stage: str) -> None:
        width = 30
        filled = int(width * percent / 100)
        bar = "#" * filled + "-" * (width - filled)
        print(f"\r[{bar}] {percent:3d}% {stage}", end="", flush=True)

    def set(self, percent: int, stage: str) -> None:
        with self._lock:
            self.percent = max(0, min(100, percent))
            self.stage = stage
            self._render(self.percent, self.stage)

    def start_auto(self, stage: str, start_percent: int, end_percent: int = 95, step: int = 1, interval: float = 1.0) -> None:
        self.set(start_percent, stage)
        self._running = True

        def _loop() -> None:
            local_percent = start_percent
            while self._running:
                time.sleep(interval)
                with self._lock:
                    if local_percent < end_percent:
                        local_percent = min(end_percent, local_percent + step)
                    self.percent = local_percent
                    self.stage = stage
                    self._render(self.percent, self.stage)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop_auto(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def finish(self, stage: str = "完成") -> None:
        self.stop_auto()
        self.set(100, stage)
        print(flush=True)


def run_cmd(cmd: list[str]) -> str:
    print(f"执行命令: {' '.join(cmd)}", flush=True)
    proc = subprocess.Popen(
        cmd,
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None
    lines: list[str] = []
    for line in proc.stdout:
        print(line, end="", flush=True)
        lines.append(line)
    return_code = proc.wait()
    if return_code != 0:
        raise RuntimeError(f"command failed (exit={return_code}): {' '.join(cmd)}")
    return "".join(lines).strip()


def copy_seed_sources(source_dir: Path) -> Path:
    expected = [
        "1.国网荆州供电公司合规风险库.xlsx",
        "2.国网荆州供电公司重要岗位履责合规义务清单.xlsx",
        "3.国网荆州供电公司业务流程管控合规管理清单.xlsx",
    ]
    target_dir = REPO_ROOT / "saves" / "jingzhou_compliance_seed" / "source"
    target_dir.mkdir(parents=True, exist_ok=True)
    source_dir = source_dir.resolve()
    target_dir = target_dir.resolve()

    if source_dir == target_dir:
        print(f"源目录已是容器可见目录，跳过复制: {target_dir}")
        return target_dir

    copied = []
    for name in expected:
        src = source_dir / name
        if not src.exists():
            raise FileNotFoundError(f"缺少源文件: {src}")
        dst = target_dir / name
        dst.write_bytes(src.read_bytes())
        copied.append(dst)
    print(f"已同步 {len(copied)} 个源文件到: {target_dir}")
    return target_dir


def run_seed_in_api(force: bool, source_dir_in_container: str, progress: ProgressBar) -> None:
    print("开始通过 docker compose 在 api 容器内执行导入...", flush=True)
    progress.start_auto(stage="导入中（容器执行）", start_percent=40, end_percent=95, step=1, interval=1.0)
    py = (
        "import asyncio;"
        "from src.services.jingzhou_compliance_seed_service import JingzhouComplianceSeedService;"
        "from pathlib import Path;"
        f"results=asyncio.run(JingzhouComplianceSeedService.seed_all(operator_id='1',department_id=1,force={str(force)},source_dir=Path('{source_dir_in_container}')));"
        "print([r.__dict__ for r in results])"
    )
    cmd = [
        "docker",
        "compose",
        "exec",
        "-T",
        "-e",
        f"YUXI_JINGZHOU_COMPLIANCE_SOURCE_DIR={source_dir_in_container}",
        "api",
        "python",
        "-c",
        py,
    ]
    try:
        output = run_cmd(cmd)
    finally:
        progress.stop_auto()
    print("导入结果:")
    print(output)


def run_seed_direct(force: bool, source_dir_in_container: str, progress: ProgressBar) -> None:
    import asyncio

    from src.services.jingzhou_compliance_seed_service import JingzhouComplianceSeedService

    print("开始在当前容器内直接执行导入...", flush=True)
    progress.start_auto(stage="导入中（容器内直跑）", start_percent=40, end_percent=95, step=1, interval=1.0)
    try:
        results = asyncio.run(
            JingzhouComplianceSeedService.seed_all(
                operator_id="1",
                department_id=1,
                force=force,
                source_dir=Path(source_dir_in_container),
            )
        )
    finally:
        progress.stop_auto()
    print("导入结果:")
    print([r.__dict__ for r in results])


def main() -> int:
    parser = argparse.ArgumentParser(description="创建并导入荆州一库两清单知识库")
    parser.add_argument(
        "--source-dir",
        default="saves/jingzhou_compliance_seed/source",
        help="三份Excel所在目录",
    )
    parser.add_argument("--force", action="store_true", help="强制重跑导入（已存在文件也重试）")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).expanduser()
    if not source_dir.is_absolute():
        source_dir = REPO_ROOT / source_dir
    if not source_dir.exists() or not source_dir.is_dir():
        print(f"源目录不存在: {source_dir}")
        return 2

    progress = ProgressBar()

    try:
        progress.set(10, "校验源目录")
        copy_seed_sources(source_dir)
        progress.set(30, "源文件准备完成")
        source_dir_in_container = "/app/saves/jingzhou_compliance_seed/source"
        if Path("/.dockerenv").exists() or which("docker") is None:
            print("检测到容器内环境，使用本进程导入模式...")
            run_seed_direct(force=args.force, source_dir_in_container=source_dir_in_container, progress=progress)
        else:
            print("检测到宿主机环境，使用 docker compose exec 导入模式...")
            run_seed_in_api(force=args.force, source_dir_in_container=source_dir_in_container, progress=progress)
        progress.finish("导入完成")
        print("完成：知识库创建与导入已执行。")
        return 0
    except Exception as exc:  # noqa: BLE001
        progress.stop_auto()
        print()
        print(f"执行失败: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
