"""审批队列存储 —— 供 chat 和 scheduler 共用

采用追加式日志 + 逻辑删除：update/delete 只追加新行，不再全量重写。
读取时按 id 去重取最新版本，跳过已删除标记。
冗余行累计超过阈值时自动压缩（compact）清理旧版本。
"""

import os
import json
import threading
from datetime import datetime

from deps import BASE_DIR

APPROVAL_QUEUE_FILE = os.path.join(BASE_DIR, "data", "approval_queue.jsonl")
_lock = threading.Lock()
_COMPACT_THRESHOLD = 100


def _read_all_lines() -> list[str]:
    if not os.path.exists(APPROVAL_QUEUE_FILE):
        return []
    lines = []
    with open(APPROVAL_QUEUE_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                lines.append(line)
    return lines


def _parse_lines(lines: list[str]) -> list[dict]:
    latest = {}
    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        oid = obj.get("id")
        if not oid:
            continue
        latest[oid] = obj

    result = []
    for obj in latest.values():
        if obj.get("_deleted"):
            continue
        result.append(obj)
    return result


def _compact():
    lines = _read_all_lines()
    current = _parse_lines(lines)
    with open(APPROVAL_QUEUE_FILE, "w", encoding="utf-8") as f:
        for item in current:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _compact_if_needed():
    lines = _read_all_lines()
    current = _parse_lines(lines)
    if len(lines) - len(current) > _COMPACT_THRESHOLD:
        with open(APPROVAL_QUEUE_FILE, "w", encoding="utf-8") as f:
            for item in current:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")


def load_approval_queue() -> list[dict]:
    with _lock:
        lines = _read_all_lines()
    return _parse_lines(lines)


def save_approval_item(item: dict):
    os.makedirs(os.path.dirname(APPROVAL_QUEUE_FILE), exist_ok=True)
    with _lock:
        with open(APPROVAL_QUEUE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def update_approval_item(approval_id: str, updates: dict) -> bool:
    items = load_approval_queue()
    for item in items:
        if item.get("id") == approval_id:
            item.update(updates)
            save_approval_item(item)
            _compact_if_needed()
            return True
    return False


def create_approval_item(task_name: str, confidence: float, output: str, mode: str = "ai_chat") -> dict:
    item = {
        "id": f"AP_{datetime.now():%Y%m%d%H%M%S}_{task_name}",
        "task_name": task_name,
        "status": "pending",
        "confidence": confidence,
        "output": output,
        "created_at": datetime.now().isoformat(),
        "mode": mode,
    }
    save_approval_item(item)
    return item


def delete_approval_item(approval_id: str) -> tuple[bool, dict | None]:
    items = load_approval_queue()
    for item in items:
        if item.get("id") == approval_id:
            save_approval_item({"id": approval_id, "_deleted": True})
            _compact_if_needed()
            return True, item
    return False, None


def get_approval_item(approval_id: str) -> dict | None:
    items = load_approval_queue()
    for item in items:
        if item.get("id") == approval_id:
            return item
    return None


def get_approval_stats() -> dict:
    items = load_approval_queue()
    return {
        "total": len(items),
        "pending": sum(1 for item in items if item.get("status") == "pending"),
        "approved": sum(1 for item in items if item.get("status") == "approved"),
        "rejected": sum(1 for item in items if item.get("status") == "rejected"),
    }