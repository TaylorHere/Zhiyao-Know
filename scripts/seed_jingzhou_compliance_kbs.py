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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_cmd(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"command failed (exit={proc.returncode}): {' '.join(cmd)}\n"
            f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
        )
    return (proc.stdout or "").strip()


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


def run_seed_in_api(force: bool, source_dir_in_container: str) -> None:
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
    output = run_cmd(cmd)
    print("导入结果:")
    print(output)


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

    try:
        copy_seed_sources(source_dir)
        run_seed_in_api(force=args.force, source_dir_in_container="/app/saves/jingzhou_compliance_seed/source")
        print("完成：知识库创建与导入已执行。")
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"执行失败: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
