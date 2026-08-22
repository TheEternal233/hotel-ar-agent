"""
可追溯操作日志 — 审计引擎

设计原则：
- 追加写入（append-only），不可篡改
- 按天自动分文件，避免单文件过大
- 线程安全，多并发环境下不丢失记录
- 与现有 approval_store.py 保持一致的 JSONL 格式
- 提供结构化查询接口

使用方式：
    from utils.audit_logger import audit

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

    # ────────── 写入 ──────────

    @staticmethod
    def _today_file() -> str:
        return os.path.join(AUDIT_DIR, f"audit_{datetime.now():%Y%m%d}.jsonl")

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
            with open(self._today_file(), "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")

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

        return deleted


# 全局单例
audit = AuditLogger()