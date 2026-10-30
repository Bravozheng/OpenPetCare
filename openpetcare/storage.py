"""Checksummed, atomic, per-dog local storage and portable archives."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid

from .models import InputError, SCHEMA_VERSION, validate_profile


class StorageError(RuntimeError):
    """Stored data is missing, damaged, or incompatible."""


def data_directory():
    override = os.environ.get("OPENPETCARE_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "OpenPetCare"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "OpenPetCare"
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))) / "openpetcare"


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def wrap(payload):
    return {"payload": payload, "sha256": hashlib.sha256(canonical(payload)).hexdigest()}


def unwrap(envelope):
    if not isinstance(envelope, dict) or set(envelope) != {"payload", "sha256"}:
        raise StorageError("文件封装格式无效")
    if hashlib.sha256(canonical(envelope["payload"])).hexdigest() != envelope["sha256"]:
        raise StorageError("文件校验失败；请从备份恢复")
    return envelope["payload"]


def read_json(path):
    try:
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise StorageError("无法读取或解析文件: " + str(path)) from exc


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix=".opc-", suffix=".tmp", dir=str(path.parent))
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
        if hasattr(os, "O_DIRECTORY"):
            directory_fd = os.open(str(path.parent), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _valid_id(dog_id):
    try:
        normalized = str(uuid.UUID(dog_id))
    except (TypeError, ValueError, AttributeError):
        raise InputError("犬只 ID 必须是 UUID")
    if normalized != dog_id:
        raise InputError("犬只 ID 格式无效")
    return normalized


def _valid_timestamp(value, field):
    if not isinstance(value, str):
        raise StorageError(field + " 时间格式无效")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise StorageError(field + " 时间格式无效") from exc
    if parsed.tzinfo is None:
        raise StorageError(field + " 必须包含时区")


def _exact_keys(value, expected, field):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise StorageError(field + " 结构无效")


def _validate_history(record):
    dog_id = record["profile"]["id"]
    plan_keys = {
        "id", "created_at", "status", "profile_revision", "profile_snapshot",
        "care_snapshot", "confirmed_from_proposal_id", "restored_from_plan_id",
    }
    proposal_keys = {
        "id", "created_at", "base_revision", "patch", "candidate_profile",
        "candidate_daily", "changes", "status", "before_feeding", "after_feeding",
    }
    plan_ids = []
    for index, plan in enumerate(record["plans"]):
        field = "plans[{}]".format(index)
        _exact_keys(plan, plan_keys, field)
        plan_ids.append(_valid_id(plan["id"]))
        _valid_timestamp(plan["created_at"], field + ".created_at")
        if plan["status"] not in ("complete", "limited"):
            raise StorageError(field + " 状态无效")
        if (isinstance(plan["profile_revision"], bool)
                or not isinstance(plan["profile_revision"], int)
                or not 1 <= plan["profile_revision"] <= record["profile_revision"]):
            raise StorageError(field + " 档案版本无效")
        try:
            validate_profile(plan["profile_snapshot"])
        except (InputError, KeyError, TypeError) as exc:
            raise StorageError(field + " 档案快照无效: " + str(exc)) from exc
        if plan["profile_snapshot"]["id"] != dog_id:
            raise StorageError(field + " 犬只 ID 不一致")
        if not isinstance(plan["care_snapshot"], dict) or plan["care_snapshot"].get("dog_id") != dog_id:
            raise StorageError(field + " 照护快照无效")
        for key in ("confirmed_from_proposal_id", "restored_from_plan_id"):
            if plan[key] is not None:
                _valid_id(plan[key])
        if (plan["confirmed_from_proposal_id"] is None) == (plan["restored_from_plan_id"] is None):
            raise StorageError(field + " 必须且只能记录一种版本来源")
    if len(plan_ids) != len(set(plan_ids)):
        raise StorageError("计划 ID 重复")

    proposal_ids = []
    for index, proposal in enumerate(record["proposals"]):
        field = "proposals[{}]".format(index)
        _exact_keys(proposal, proposal_keys, field)
        proposal_ids.append(_valid_id(proposal["id"]))
        _valid_timestamp(proposal["created_at"], field + ".created_at")
        if proposal["status"] not in ("pending", "confirmed", "obsolete"):
            raise StorageError(field + " 状态无效")
        if (isinstance(proposal["base_revision"], bool)
                or not isinstance(proposal["base_revision"], int)
                or not 1 <= proposal["base_revision"] <= record["profile_revision"]):
            raise StorageError(field + " 基础版本无效")
        if not isinstance(proposal["patch"], dict):
            raise StorageError(field + " 补丁无效")
        try:
            validate_profile(proposal["candidate_profile"])
        except (InputError, KeyError, TypeError) as exc:
            raise StorageError(field + " 候选档案无效: " + str(exc)) from exc
        if proposal["candidate_profile"]["id"] != dog_id:
            raise StorageError(field + " 犬只 ID 不一致")
        if not isinstance(proposal["candidate_daily"], dict) or proposal["candidate_daily"].get("dog_id") != dog_id:
            raise StorageError(field + " 候选照护方案无效")
        if not isinstance(proposal["changes"], list):
            raise StorageError(field + " 变更列表无效")
        for change in proposal["changes"]:
            _exact_keys(change, {"field", "before", "after"}, field + ".changes[]")
            if not isinstance(change["field"], str) or not change["field"]:
                raise StorageError(field + " 变更字段无效")
        for key in ("before_feeding", "after_feeding"):
            if proposal[key] is not None and not isinstance(proposal[key], dict):
                raise StorageError(field + "." + key + " 无效")
    if len(proposal_ids) != len(set(proposal_ids)):
        raise StorageError("提案 ID 重复")

    plan_id_set = set(plan_ids)
    proposal_id_set = set(proposal_ids)
    for plan in record["plans"]:
        source_proposal = plan["confirmed_from_proposal_id"]
        source_plan = plan["restored_from_plan_id"]
        if source_proposal is not None and source_proposal not in proposal_id_set:
            raise StorageError("计划引用的提案不存在")
        if source_plan is not None and (source_plan not in plan_id_set or source_plan == plan["id"]):
            raise StorageError("恢复来源计划不存在或引用自身")

    for index, event in enumerate(record["events"]):
        field = "events[{}]".format(index)
        _exact_keys(event, {"at", "type", "details"}, field)
        _valid_timestamp(event["at"], field + ".at")
        if not isinstance(event["type"], str) or not event["type"] or not isinstance(event["details"], dict):
            raise StorageError(field + " 内容无效")


def validate_record(record):
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
        raise StorageError("数据版本不兼容；保留原文件并使用兼容版本迁移")
    required = {"schema_version", "profile_revision", "profile", "active_plan_id", "plans", "proposals", "events"}
    if set(record) != required:
        raise StorageError("档案结构不完整")
    if (isinstance(record["profile_revision"], bool)
            or not isinstance(record["profile_revision"], int)
            or record["profile_revision"] < 1):
        raise StorageError("档案版本无效")
    if not all(isinstance(record[key], list) for key in ("plans", "proposals", "events")):
        raise StorageError("历史记录结构无效")
    try:
        validate_profile(record["profile"])
    except (InputError, KeyError, TypeError) as exc:
        raise StorageError("档案内容无效: " + str(exc)) from exc
    try:
        _validate_history(record)
        if record["active_plan_id"] is not None:
            _valid_id(record["active_plan_id"])
            if not any(plan["id"] == record["active_plan_id"] for plan in record["plans"]):
                raise StorageError("当前计划版本不存在")
    except InputError as exc:
        raise StorageError("历史记录内容无效: " + str(exc)) from exc


class Store:
    def __init__(self, root=None):
        self.root = Path(root) if root is not None else data_directory()
        self.dogs = self.root / "dogs"
        self.backups = self.root / "backups"

    def _path(self, dog_id):
        return self.dogs / (_valid_id(dog_id) + ".json")

    def get(self, dog_id):
        path = self._path(dog_id)
        if not path.is_file():
            raise StorageError("找不到犬只档案: " + dog_id)
        record = unwrap(read_json(path))
        validate_record(record)
        if record["profile"]["id"] != dog_id:
            raise StorageError("文件名与档案 ID 不一致")
        return record

    def list(self):
        if not self.dogs.exists():
            return []
        return [self.get(path.stem) for path in sorted(self.dogs.glob("*.json"))]

    def save(self, record, expected_revision=None, create=False):
        validate_record(record)
        path = self._path(record["profile"]["id"])
        if create:
            if path.exists():
                raise StorageError("档案已存在")
        elif expected_revision is not None:
            current = self.get(record["profile"]["id"])
            if current["profile_revision"] != expected_revision:
                raise StorageError("档案已被其他操作更新，请重新读取后再试")
        atomic_json(path, wrap(record))

    def archive(self):
        records = self.list()
        payload = {
            "archive_version": 1,
            "created_at": now_iso(),
            "records": records,
        }
        return wrap(payload)

    def export(self, path, overwrite=False):
        destination = Path(path).expanduser()
        if destination.exists() and not overwrite:
            raise StorageError("导出文件已存在；请换路径或显式允许覆盖")
        atomic_json(destination, self.archive())
        return destination

    def backup(self):
        name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8] + ".json"
        return self.export(self.backups / name)

    def import_archive(self, path, replace=False):
        payload = unwrap(read_json(Path(path).expanduser()))
        if (not isinstance(payload, dict)
                or set(payload) != {"archive_version", "created_at", "records"}
                or payload.get("archive_version") != 1
                or not isinstance(payload.get("records"), list)):
            raise StorageError("备份格式不兼容")
        _valid_timestamp(payload["created_at"], "created_at")
        records = payload["records"]
        ids = []
        for record in records:
            validate_record(record)
            ids.append(record["profile"]["id"])
        if len(ids) != len(set(ids)):
            raise StorageError("备份中犬只 ID 重复")
        collisions = [dog_id for dog_id in ids if self._path(dog_id).exists()]
        if collisions and not replace:
            raise StorageError("目标中已有同 ID 档案；恢复需显式指定 --replace")
        originals = {}
        for dog_id in ids:
            target = self._path(dog_id)
            if target.exists():
                self.get(dog_id)
                originals[dog_id] = read_json(target)
            else:
                originals[dog_id] = None
        try:
            for record in records:
                target = self._path(record["profile"]["id"])
                self.save(record, create=not target.exists())
        except Exception as exc:
            rollback_errors = []
            for dog_id, envelope in originals.items():
                target = self._path(dog_id)
                try:
                    if envelope is None:
                        if target.exists():
                            target.unlink()
                    else:
                        atomic_json(target, envelope)
                except OSError as rollback_exc:
                    rollback_errors.append(str(rollback_exc))
            if rollback_errors:
                raise StorageError("导入失败且回滚不完整；请从导入前备份恢复") from exc
            raise StorageError("导入失败，已恢复导入前数据") from exc
        return len(records)
