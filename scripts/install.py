#!/usr/bin/env python3
"""Copy a minimal OpenPetCare Skill bundle into a local host skill directory."""

import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile


SOURCE = Path(__file__).resolve().parents[1]
FILES = ["SKILL.md", "scripts/opc.py", "docs/DATA_SCHEMA.md",
         "docs/SCIENCE_SOURCES.md", "docs/SAFETY_POLICY.md"]


def destination(host, scope, project):
    if scope == "project":
        if not project:
            raise ValueError("项目级安装需要 --project 路径")
        base = Path(project).expanduser().resolve()
        folder = ".agents" if host == "codex" else ".claude"
        return base / folder / "skills" / "openpetcare"
    folder = ".agents" if host == "codex" else ".claude"
    return Path.home() / folder / "skills" / "openpetcare"


def install(target, replace=False):
    target = Path(target).expanduser()
    if target.is_symlink():
        raise ValueError("目标是符号链接；请先手动检查，不自动替换")
    if target.exists() and not replace:
        raise ValueError("Skill 已存在；若确认更新可加 --replace。犬只数据目录不会被触碰")
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".openpetcare-install-", dir=str(target.parent)))
    previous = None
    try:
        for relative in FILES:
            source = SOURCE / relative
            output = staging / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)
        shutil.copytree(SOURCE / "openpetcare", staging / "openpetcare",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if target.exists():
            previous = target.with_name(".openpetcare-previous-" + next(tempfile._get_candidate_names()))
            os.replace(target, previous)
        os.replace(staging, target)
        if previous is not None:
            shutil.rmtree(previous)
        return target
    except Exception:
        if previous is not None and previous.exists() and not target.exists():
            os.replace(previous, target)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main(argv=None):
    p = argparse.ArgumentParser(description="安装 OpenPetCare 本地 Agent Skill")
    p.add_argument("host", choices=("codex", "claude"))
    p.add_argument("--scope", choices=("user", "project"), default="user")
    p.add_argument("--project", help="项目级安装的项目根目录")
    p.add_argument("--target", help="仅供测试或自定义安装：完整 Skill 目标目录")
    p.add_argument("--replace", action="store_true", help="更新已有的普通目录安装")
    args = p.parse_args(argv)
    try:
        target = Path(args.target) if args.target else destination(args.host, args.scope, args.project)
        print(install(target, args.replace))
        return 0
    except (OSError, ValueError) as exc:
        print("安装失败: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
