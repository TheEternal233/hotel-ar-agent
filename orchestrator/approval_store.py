"""审批队列存储 —— 供 chat 和 scheduler 共用

采用追加式日志 + 逻辑删除：update/delete 只追加新行，不再全量重写。
读取时按 id 去重取最新版本，跳过已删除标记。
冗余行累计超过阈值时自动压缩（compact）清理旧版本。

性能优化：内存缓存 id -> item 映射，避免每次查询都全量读取+解析文件。
写入时同步更新缓存，读取时直接从缓存返回，O(1) 查询。
"""

import os
import json
import threading
from datetime import datetime

from deps import BASE_DIR

APPROVAL_QUEUE_FILE = os.path.join(BASE_DIR, "data", "approval_queue.jsonl")
_lock = threading.Lock()
_COMPACT_THRESHOLD = 100

# 内存缓存：id -> 最新版本 item（含 _deleted 标记），避免每次全量读盘
_cache: dict[str, dict] = {}
_cache_initialized: bool = False
_total_lines: int = 0


def _ensure_cache():
    global _cache, _cache_initialized, _total_lines
    if _cache_initialized:
        return
    _cache = {}
    _total_lines = 0
    if os.path.exists(APPROVAL_QUEUE_FILE):
        with open(APPROVAL_QUEUE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                _total_lines += 1
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                oid = obj.get("id")
                if not oid:
                    continue
                _cache[oid] = obj
    _cache_initialized = True


def _append_and_cache(item: dict):
    global _total_lines
    os.makedirs(os.path.dirname(APPROVAL_QUEUE_FILE), exist_ok=True)
    with open(APPROVAL_QUEUE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")
    _total_lines += 1
    oid = item.get("id")
    if oid:
        _cache[oid] = item


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
    with _lock:
        _ensure_cache()
        global _total_lines
        current = [obj for obj in _cache.values() if not obj.get("_deleted")]
        with open(APPROVAL_QUEUE_FILE, "w", encoding="utf-8") as f:
            for item in current:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        _total_lines = len(current)


def _compact_if_needed():
    global _total_lines
    with _lock:
        _ensure_cache()
        current_count = sum(1 for obj in _cache.values() if not obj.get("_deleted"))
        if _total_lines - current_count > _COMPACT_THRESHOLD:
            current = [obj for obj in _cache.values() if not obj.get("_deleted")]
            with open(APPROVAL_QUEUE_FILE, "w", encoding="utf-8") as f:
                for item in current:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            _total_lines = len(current)


def load_approval_queue() -> list[dict]:
    with _lock:
        _ensure_cache()
        return [obj for obj in _cache.values() if not obj.get("_deleted")]


def save_approval_item(item: dict):
    with _lock:
        _ensure_cache()
        _append_and_cache(item)


def update_approval_item(approval_id: str, updates: dict) -> bool:
    with _lock:
        _ensure_cache()
        item = _cache.get(approval_id)
        if item is None or item.get("_deleted"):
            return False
        item.update(updates)
        _append_and_cache(item)
    _compact_if_needed()
    return True


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
    with _lock:
        _ensure_cache()
        item = _cache.get(approval_id)
        if item is None or item.get("_deleted"):
            return False, None
        deleted_marker = {"id": approval_id, "_deleted": True}
        _append_and_cache(deleted_marker)
    _compact_if_needed()
    return True, item


def get_approval_item(approval_id: str) -> dict | None:
    with _lock:
        _ensure_cache()
        item = _cache.get(approval_id)
        if item is None or item.get("_deleted"):
            return None
        return item


def get_approval_stats() -> dict:
    with _lock:
        _ensure_cache()
        items = [obj for obj in _cache.values() if not obj.get("_deleted")]
        return {
            "total": len(items),
            "pending": sum(1 for item in items if item.get("status") == "pending"),
            "approved": sum(1 for item in items if item.get("status") == "approved"),
            "rejected": sum(1 for item in items if item.get("status") == "rejected"),
        }