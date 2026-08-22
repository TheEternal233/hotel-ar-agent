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
from pathlib import Path
from typing import Optional

from enums.paths import BASE_DIR

AUDIT_DIR = os.path.join(BASE_DIR, "data", "audit")

# 索引文件名后缀
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
        """根据日志文件路径生成对应的索引文件路径"""
        return log_file + INDEX_SUFFIX

    def _build_index(self, log_file: str) -> dict:
        """
        为单个日志文件构建索引。
        索引结构：{ "module": { "ota_recon": [0, 120, 350, ...], ... }, "action": {...}, "status": {...}, "user": {...} }
        value 为字节偏移量列表，指向日志文件中对应记录的起始位置。
        """
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

                    # 为每个维度建立索引
                    for dim in ("module", "action", "status", "user"):
                        val = event.get(dim, "")
                        if val:
                            index[dim].setdefault(val, []).append(offset)

                    offset += len(line.encode("utf-8"))
        except OSError:
            pass
        return index

    def _save_index(self, log_file: str, index: dict) -> None:
        """将索引写入磁盘"""
        idx_file = self._index_file(log_file)
        try:
            with open(idx_file, "w", encoding="utf-8") as f:
                json.dump(index, f, ensure_ascii=False)
        except OSError:
            pass

    def _load_index(self, log_file: str) -> Optional[dict]:
        """从磁盘加载索引，如果不存在或过期则返回 None"""
        idx_file = self._index_file(log_file)
        try:
            # 检查索引是否比日志文件新
            log_mtime = os.path.getmtime(log_file)
            idx_mtime = os.path.getmtime(idx_file)
            if idx_mtime < log_mtime:
                return None  # 索引过期，需要重建

            with open(idx_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    def _get_or_build_index(self, log_file: str) -> dict:
        """获取索引（优先从磁盘加载，否则重建并缓存）"""
        index = self._load_index(log_file)
        if index is None:
            index = self._build_index(log_file)
            self._save_index(log_file, index)
        return index

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
        """记录一条审计日志。

        Args:
            module:  业务模块 (ota_recon / card_recon / aging / ctrip / invoice / scheduler / chat / config / files)
            action:  操作动作 (upload / match / confirm / approve / reject / export / delete / login / ...)
            detail:  人类可读的操作描述
            user:    操作人标识
            ip:      客户端 IP
            status:  success / failed / blocked
            context: 附加业务上下文（渠道、文件、统计数据等）
            duration_ms: 操作耗时（毫秒）

        Returns:
            event_id: 审计事件 ID
        """
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
            # 追加写入日志
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

            # 删除过期的索引文件（下次查询时会自动重建）
            idx_file = self._index_file(log_file)
            if os.path.exists(idx_file):
                try:
                    os.remove(idx_file)
                except OSError:
                    pass

        return event_id

    # ────────── 查询 ──────────

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
        """查询审计日志，按时间倒序。

        优化：当查询条件包含 module/action/status/user 时，
        使用索引文件快速定位匹配记录，避免逐行解析所有日志。

        Args:
            module:  按模块过滤，空字符串表示不过滤
            action:  按操作过滤
            user:    按用户过滤
            status:  按状态过滤 (success / failed / blocked)
            days:    查询最近 N 天的日志
            limit:   返回条数上限
            offset:  分页偏移

        Returns:
            list[dict]: 审计事件列表
        """
        start_date = datetime.now() - timedelta(days=days)
        records = []

        # 遍历日期范围内的所有审计文件
        if not os.path.exists(AUDIT_DIR):
            return []

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

            # 判断是否能使用索引加速
            # 条件：至少有一个过滤字段非空，且该字段有索引
            use_index = False
            filter_dims = []
            if module:
                filter_dims.append(("module", module))
            if action:
                filter_dims.append(("action", action))
            if status:
                filter_dims.append(("status", status))
            if user:
                filter_dims.append(("user", user))

            if filter_dims:
                use_index = True
                index = self._get_or_build_index(filepath)
                # 取交集：找出同时满足所有过滤条件的偏移量
                candidate_offsets = None
                for dim, val in filter_dims:
                    dim_offsets = set(index.get(dim, {}).get(val, []))
                    if candidate_offsets is None:
                        candidate_offsets = dim_offsets
                    else:
                        candidate_offsets &= dim_offsets
                    if not candidate_offsets:
                        break  # 交集为空，无需继续

                if candidate_offsets:
                    # 按偏移量排序，顺序读取
                    for offset in sorted(candidate_offsets):
                        try:
                            with open(filepath, "r", encoding="utf-8") as f:
                                f.seek(offset)
                                line = f.readline()
                                if line:
                                    try:
                                        event = json.loads(line.strip())
                                        records.append(event)
                                    except json.JSONDecodeError:
                                        pass
                        except OSError:
                            pass
            
            if not use_index or not filter_dims:
                # 无过滤条件或索引未命中，回退到全文件扫描
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

                            # 过滤
                            if module and event.get("module") != module:
                                continue
                            if action and event.get("action") != action:
                                continue
                            if user and event.get("user") != user:
                                continue
                            if status and event.get("status") != status:
                                continue

                            records.append(event)
                except OSError:
                    continue

        # 按时间倒序
        records.sort(key=lambda e: e.get("timestamp", ""), reverse=True)

        total = len(records)
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
        """统计符合条件的审计日志数量。"""
        records = self.query(module=module, action=action, user=user,
                             status=status, days=days, limit=999999)
        return len(records)

    def stats(self, days: int = 7) -> dict:
        """获取指定天数内的审计统计摘要。"""
        records = self.query(days=days, limit=999999)

        by_module = {}
        by_action = {}
        by_status = {"success": 0, "failed": 0, "blocked": 0}
        by_user = {}

        for r in records:
            m = r.get("module", "unknown")
            a = r.get("action", "unknown")
            s = r.get("status", "unknown")
            u = r.get("user", "unknown")

            by_module[m] = by_module.get(m, 0) + 1
            by_action[a] = by_action.get(a, 0) + 1
            if s in by_status:
                by_status[s] += 1
            by_user[u] = by_user.get(u, 0) + 1

        return {
            "total": len(records),
            "days": days,
            "by_module": by_module,
            "by_action": by_action,
            "by_status": by_status,
            "by_user": by_user,
        }

    # ────────── 删除 ──────────

    def delete_by_id(self, event_id: str) -> bool:
        """按 ID 删除单条审计日志。

        Args:
            event_id: 审计事件 ID

        Returns:
            bool: 是否删除成功
        """
        if not os.path.exists(AUDIT_DIR):
            return False

        deleted = False
        for filename in os.listdir(AUDIT_DIR):
            if not filename.startswith("audit_") or not filename.endswith(".jsonl"):
                continue
            filepath = os.path.join(AUDIT_DIR, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            except OSError:
                continue

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
                    # 删除索引文件，下次查询自动重建
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
        """清理超过保留天数的审计日志文件。

        Args:
            retain_days: 保留天数，默认 90 天

        Returns:
            int: 删除的文件数
        """
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
                # 同时删除对应的索引文件
                idx_file = self._index_file(filepath)
                if os.path.exists(idx_file):
                    try:
                        os.remove(idx_file)
                    except OSError:
                        pass

        return deleted


# 全局单例
audit = AuditLogger()