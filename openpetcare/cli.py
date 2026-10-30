"""JSON command line interface for local AI hosts."""

import argparse
import json
from pathlib import Path
import sys

from .models import InputError
from .service import (create_profile, update_profile, daily_care, propose_plan,
                      confirm_plan, plan_history, restore_plan)
from .storage import Store, StorageError, data_directory


def _json_arg(value):
    if value == "-":
        raw = sys.stdin.read()
    elif value.startswith("@"):
        raw = Path(value[1:]).read_text(encoding="utf-8")
    else:
        raw = value
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise InputError("输入不是有效 JSON: " + str(exc)) from exc
    if not isinstance(parsed, dict):
        raise InputError("请输入 JSON 对象")
    return parsed


def parser():
    top = argparse.ArgumentParser(prog="opc.py", description="OpenPetCare 本地犬只照护工具，输出 JSON")
    top.add_argument("--data-dir", help="仅用于测试或明确迁移；默认系统持久应用数据目录")
    sections = top.add_subparsers(dest="section", required=True)

    profile = sections.add_parser("profile", help="犬只档案")
    actions = profile.add_subparsers(dest="action", required=True)
    p = actions.add_parser("create")
    p.add_argument("--json", required=True, help="JSON、@文件或 -（标准输入）")
    p = actions.add_parser("get")
    p.add_argument("--dog", required=True)
    actions.add_parser("list")
    p = actions.add_parser("update")
    p.add_argument("--dog", required=True)
    p.add_argument("--patch", required=True, help="JSON、@文件或 -")

    p = sections.add_parser("daily", help="生成当日照护方案")
    p.add_argument("--dog", required=True)
    p.add_argument("--date", help="YYYY-MM-DD；默认本机日期")

    plan = sections.add_parser("plan", help="提案、确认与历史")
    actions = plan.add_subparsers(dest="action", required=True)
    p = actions.add_parser("propose")
    p.add_argument("--dog", required=True)
    p.add_argument("--patch", required=True, help="候选档案字段 JSON、@文件或 -")
    p = actions.add_parser("confirm")
    p.add_argument("--dog", required=True)
    p.add_argument("--proposal", required=True)
    p = actions.add_parser("history")
    p.add_argument("--dog", required=True)
    p = actions.add_parser("restore")
    p.add_argument("--dog", required=True)
    p.add_argument("--version", required=True)

    data = sections.add_parser("data", help="备份、导出、导入")
    actions = data.add_subparsers(dest="action", required=True)
    actions.add_parser("backup")
    p = actions.add_parser("export")
    p.add_argument("--path", required=True)
    p.add_argument("--overwrite", action="store_true")
    p = actions.add_parser("import")
    p.add_argument("--path", required=True)
    p.add_argument("--replace", action="store_true")
    sections.add_parser("where", help="显示数据目录")
    return top


def run(args):
    store = Store(args.data_dir)
    if args.section == "where":
        return {"data_dir": str(store.root)}
    if args.section == "profile":
        if args.action == "create":
            return create_profile(store, _json_arg(args.json))
        if args.action == "get":
            record = store.get(args.dog)
            return {"profile": record["profile"], "profile_revision": record["profile_revision"],
                    "active_plan_id": record["active_plan_id"]}
        if args.action == "list":
            return {"dogs": [{"id": record["profile"]["id"], "name": record["profile"]["name"]}
                             for record in store.list()]}
        return update_profile(store, args.dog, _json_arg(args.patch))
    if args.section == "daily":
        return daily_care(store, args.dog, args.date)
    if args.section == "plan":
        if args.action == "propose":
            return propose_plan(store, args.dog, _json_arg(args.patch))
        if args.action == "confirm":
            return confirm_plan(store, args.dog, args.proposal)
        if args.action == "history":
            return plan_history(store, args.dog)
        return restore_plan(store, args.dog, args.version)
    if args.action == "backup":
        return {"backup_path": str(store.backup())}
    if args.action == "export":
        return {"export_path": str(store.export(args.path, args.overwrite))}
    return {"imported_records": store.import_archive(args.path, args.replace)}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        output = run(args)
    except (InputError, StorageError, OSError, ValueError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
