"""
可追溯操作日志 — 审计引擎

设计原则：
- 追加写入（append-only），不可篡改
- 按天自动分文件，避免单文件过大
- 线程安全，多并发环境下不丢失记录
- 与现有 approval_store.py 保持一致的 JSONL 格式
- 提供结构化查询接口
- 按模块/动作/状态/用户建立索引，加速查询过滤

使用方式：
    from utils.audit_engine import audit

    audit.log("ota_recon", "confirm", "确认携程客房对账，匹配120笔差异3笔",
              user="财务张三", context={"channel": "携程客房", "stats": {...}})

    # 查询
    records = audit.query(module="ota_recon", days=7)
"""

import json
import os
import threading
import uuid
from datetime import datetime, timedelta
from typing import Optional

from enums.paths import BASE_DIR

AUDIT_DIR = os.path.join(BASE_DIR, "data", "audit")

INDEX_SUFFIX = ".idx.json"


class AuditLogger:
    """审计日志记录器（单例模式，线程安全）"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._write_lock = threading.Lock()
        os.makedirs(AUDIT_DIR, exist_ok=True)

    # ────────── 内部工具 ──────────

    @staticmethod
    def _today_file() -> str:
        return os.path.join(AUDIT_DIR, f"audit_{datetime.now():%Y%m%d}.jsonl")

    @staticmethod
    def _index_file(log_file: str) -> str:
        return log_file + INDEX_SUFFIX

    def _build_index(self, log_file: str) -> dict:
        index = {"module": {}, "action": {}, "status": {}, "user": {}}
        if not os.path.exists(log_file):
            return index
        try:
            with open(log_file, "r", encoding="utf-8") as f:
                offset = 0
                for line in f:
                    line_stripped = line.strip()
                    if not line_stripped:
                        offset += len(line.encode("utf-8"))
                        continue
                    try:
                        event = json.loads(line_stripped)
                    except json.JSONDecodeError:
                        offset += len(line.encode("utf-8"))
                        continue

                    for dim in ("module", "action", "status", "user"):
                        val = event.get(dim, "")
                        if val:
                            index[dim].setdefault(val, []).append(offset)

                    offset += len(line.encode("utf-8"))
        except OSError:
            pass
        return index

    def _save_index(self, log_file: str, index: dict) -> None:
        idx_file = self._index_file(log_file)
        try:
            with open(idx_file, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False)
        except OSError:
            pass

    def _load_index(self, log_file: str) -> Optional[dict]:
        idx_file = self._index_file(log_file)
        try:
            log_mtime = os.path.getmtime(log_file)
            idx_mtime = os.path.getmtime(idx_file)
            if idx_mtime < log_mtime:
                return None
            with open(idx_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _get_or_build_index(self, log_file: str) -> dict:
        index = self._load_index(log_file)
        if index is None:
            index = self._build_index(log_file)
            self._save_index(log_file, index)
        return index

    def _update_index_incremental(self, log_file: str, event: dict, offset: int) -> None:
        if not os.path.exists(log_file):
            return
        index = self._load_index(log_file)
        if index is None:
            index = self._build_index(log_file)
        else:
            for dim in ("module", "action", "status", "user"):
                val = event.get(dim, "")
                if val:
                    index.setdefault(dim, {}).setdefault(val, []).append(offset)
        self._save_index(log_file, index)

    # ────────── 写入 ──────────

    def log(
        self,
        module: str,
        action: str,
        detail: str = "",
        *,
        user: str = "system",
        ip: str = "",
        status: str = "success",
        context: dict | None = None,
        duration_ms: int = 0,
    ) -> str:
        event_id = f"AUD_{datetime.now():%Y%m%d%H%M%S}_{uuid.uuid4().hex[:6]}"
        event = {
            "id": event_id,
            "timestamp": datetime.now().isoformat(),
            "user": user,
            "ip": ip,
            "module": module,
            "action": action,
            "status": status,
            "detail": detail,
            "context": context or {},
            "duration_ms": duration_ms,
        }

        with self._write_lock:
            log_file = self._today_file()

            if os.path.exists(log_file):
                offset = os.path.getsize(log_file)
            else:
                offset = 0

            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

            self._update_index_incremental(log_file, event, offset)

        return event_id

    # ────────── 查询 ──────────

    def _query_indexed(
        self, filepath: str, filter_dims: list, records: list
    ) -> None:
        index = self._get_or_build_index(filepath)

        candidate_offsets = None
        for dim, val in filter_dims:
            dim_offsets = set(index.get(dim, {}).get(val, []))
            if candidate_offsets is None:
                candidate_offsets = dim_offsets
            else:
                candidate_offsets &= dim_offsets
            if not candidate_offsets:
                return

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for off in sorted(candidate_offsets):
                    f.seek(off)
                    line = f.readline()
                    if line:
                        try:
                            records.append(json.loads(line.strip()))
                        except json.JSONDecodeError:
                            pass
        except OSError:
            pass

    @staticmethod
    def _query_scan(filepath, filter_dims, records):
        dim_map = dict(filter_dims)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if all(event.get(dim) == val for dim, val in filter_dims):
                        records.append(event)
        except OSError:
            pass

    def query(
        self,
        *,
        module: str = "",
        action: str = "",
        user: str = "",
        status: str = "",
        days: int = 7,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        start_date = datetime.now() - timedelta(days=days)
        records = []

        if not os.path.exists(AUDIT_DIR):
            return []

        filter_dims = []
        if module:
            filter_dims.append(("module", module))
        if action:
            filter_dims.append(("action", action))
        if status:
            filter_dims.append(("status", status))
        if user:
            filter_dims.append(("user", user))

        for filename in sorted(os.listdir(AUDIT_DIR), reverse=True):
            if not filename.startswith("audit_") or not filename.endswith(".jsonl"):
                continue

            file_date_str = filename.replace("audit_", "").replace(".jsonl", "")
            try:
                file_date = datetime.strptime(file_date_str, "%Y%m%d")
            except ValueError:
                continue

            if file_date < start_date.replace(hour=0, minute=0, second=0, microsecond=0):
                continue

            filepath = os.path.join(AUDIT_DIR, filename)

            if filter_dims:
                self._query_indexed(filepath, filter_dims, records)
            else:
                self._query_scan(filepath, filter_dims, records)

        records.sort(key=lambda e: e.get("timestamp", ""), reverse=True)
        return records[offset: offset + limit]

    def count(
        self,
        *,
        module: str = "",
        action: str = "",
        user: str = "",
        status: str = "",
        days: int = 7,
    ) -> int:
        start_date = datetime.now() - timedelta(days=days)
        total = 0

        if not os.path.exists(AUDIT_DIR):
            return 0

        filter_dims = []
        if module:
            filter_dims.append(("module", module))
        if action:
            filter_dims.append(("action", action))
        if status:
            filter_dims.append(("status", status))
        if user:
            filter_dims.append(("user", user))

        for filename in sorted(os.listdir(AUDIT_DIR), reverse=True):
            if not filename.startswith("audit_") or not filename.endswith(".jsonl"):
                continue

            file_date_str = filename.replace("audit_", "").replace(".jsonl", "")
            try:
                file_date = datetime.strptime(file_date_str, "%Y%m%d")
            except ValueError:
                continue

            if file_date < start_date.replace(hour=0, minute=0, second=0, microsecond=0):
                continue

            filepath = os.path.join(AUDIT_DIR, filename)

            if filter_dims:
                index = self._get_or_build_index(filepath)
                candidate_offsets = None
                for dim, val in filter_dims:
                    dim_offsets = set(index.get(dim, {}).get(val, []))
                    if candidate_offsets is None:
                        candidate_offsets = dim_offsets
                    else:
                        candidate_offsets &= dim_offsets
                    if not candidate_offsets:
                        break
                if candidate_offsets:
                    total += len(candidate_offsets)
            else:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        total += sum(1 for _ in f)
                except OSError:
                    pass

        return total

    def stats(self, days: int = 7) -> dict:
        start_date = datetime.now() - timedelta(days=days)

        by_module = {}
        by_action = {}
        by_status = {"success": 0, "failed": 0, "blocked": 0}
        by_user = {}
        total = 0

        if not os.path.exists(AUDIT_DIR):
            return {
                "total": 0, "days": days,
                "by_module": {}, "by_action": {},
                "by_status": by_status, "by_user": {},
            }

        for filename in sorted(os.listdir(AUDIT_DIR), reverse=True):
            if not filename.startswith("audit_") or not filename.endswith(".jsonl"):
                continue

            file_date_str = filename.replace("audit_", "").replace(".jsonl", "")
            try:
                file_date = datetime.strptime(file_date_str, "%Y%m%d")
            except ValueError:
                continue

            if file_date < start_date.replace(hour=0, minute=0, second=0, microsecond=0):
                continue

            filepath = os.path.join(AUDIT_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        m = event.get("module", "unknown")
                        a = event.get("action", "unknown")
                        s = event.get("status", "unknown")
                        u = event.get("user", "unknown")

                        by_module[m] = by_module.get(m, 0) + 1
                        by_action[a] = by_action.get(a, 0) + 1
                        if s in by_status:
                            by_status[s] += 1
                        by_user[u] = by_user.get(u, 0) + 1
                        total += 1
            except OSError:
                pass

        return {
            "total": total,
            "days": days,
            "by_module": by_module,
            "by_action": by_action,
            "by_status": by_status,
            "by_user": by_user,
        }

    # ────────── 删除 ──────────

    def delete_by_id(self, event_id: str) -> bool:
        if not os.path.exists(AUDIT_DIR):
            return False

        for filename in os.listdir(AUDIT_DIR):
            if not filename.startswith("audit_") or not filename.endswith(".jsonl"):
                continue
            filepath = os.path.join(AUDIT_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError:
                continue

            deleted = False
            new_lines = []
            for line in lines:
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                try:
                    event = json.loads(line_stripped)
                except json.JSONDecodeError:
                    new_lines.append(line)
                    continue
                if event.get("id") == event_id:
                    deleted = True
                    continue
                new_lines.append(line)

            if deleted:
                with self._write_lock:
                    with open(filepath, "w", encoding="utf-8") as f:
                        f.writelines(new_lines)
                    idx_file = self._index_file(filepath)
                    if os.path.exists(idx_file):
                        try:
                            os.remove(idx_file)
                        except OSError:
                            pass
                return True

        return False

    # ────────── 清理 ──────────

    def cleanup(self, retain_days: int = 90) -> int:
        cutoff = datetime.now() - timedelta(days=retain_days)
        deleted = 0

        if not os.path.exists(AUDIT_DIR):
            return 0

        for filename in os.listdir(AUDIT_DIR):
            if not filename.startswith("audit_") or not filename.endswith(".jsonl"):
                continue
            file_date_str = filename.replace("audit_", "").replace(".jsonl", "")
            try:
                file_date = datetime.strptime(file_date_str, "%Y%m%d")
            except ValueError:
                continue
            if file_date < cutoff:
                filepath = os.path.join(AUDIT_DIR, filename)
                try:
                    os.remove(filepath)
                    deleted += 1
                except OSError:
                    pass
                idx_file = self._index_file(filepath)
                if os.path.exists(idx_file):
                    try:
                        os.remove(idx_file)
                    except OSError:
                        pass

        return deleted


audit = AuditLogger()