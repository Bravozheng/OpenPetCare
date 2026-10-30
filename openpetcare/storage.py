"""Checksummed, atomic, per-dog local storage and portable archives."""

from contextlib import contextmanager
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


def validate_record(record):
    if not isinstance(record, dict) or record.get("schema_version") != SCHEMA_VERSION:
        raise StorageError("数据版本不兼容；保留原文件并使用兼容版本迁移")
    required = {"schema_version", "profile_revision", "profile", "active_plan_id", "plans", "proposals", "events"}
    if set(record) != required:
        raise StorageError("档案结构不完整")
    if not isinstance(record["profile_revision"], int) or record["profile_revision"] < 1:
        raise StorageError("档案版本无效")
    if not all(isinstance(record[key], list) for key in ("plans", "proposals", "events")):
        raise StorageError("历史记录结构无效")
    try:
        validate_profile(record["profile"])
    except (InputError, KeyError, TypeError) as exc:
        raise StorageError("档案内容无效: " + str(exc)) from exc
    if record["active_plan_id"] is not None and not any(
        isinstance(plan, dict) and plan.get("id") == record["active_plan_id"]
        for plan in record["plans"]
    ):
        raise StorageError("当前计划版本不存在")


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
        if not isinstance(payload, dict) or payload.get("archive_version") != 1 or not isinstance(payload.get("records"), list):
            raise StorageError("备份格式不兼容")
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
        # Validate the entire archive before writing any record.
        for record in records:
            self.save(record, create=not replace)
        return len(records)
