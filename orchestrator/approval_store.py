"""审批队列存储 —— 供 chat 和 scheduler 共用"""

import os
import json
from datetime import datetime

from deps import BASE_DIR

APPROVAL_QUEUE_FILE = os.path.join(BASE_DIR, "data", "approval_queue.jsonl")


def load_approval_queue() -> list[dict]:
    """加载待审批队列"""
    if not os.path.exists(APPROVAL_QUEUE_FILE):
        return []
    items = []
    try:
        with open(APPROVAL_QUEUE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    items.append(json.loads(line))
    except Exception:
        pass
    return items


def save_approval_item(item: dict):
    """保存审批项到队列"""
    os.makedirs(os.path.dirname(APPROVAL_QUEUE_FILE), exist_ok=True)
    with open(APPROVAL_QUEUE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def update_approval_item(approval_id: str, updates: dict) -> bool:
    """更新审批项状态"""
    items = load_approval_queue()
    updated = False
    for item in items:
        if item.get("id") == approval_id:
            item.update(updates)
            updated = True
            break

    if updated:
        with open(APPROVAL_QUEUE_FILE, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
    return updated


def create_approval_item(task_name: str, confidence: float, output: str, mode: str = "ai_chat") -> dict:
    """创建新的审批项"""
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
    """删除审批项，返回 (是否成功, 被删除的项)"""
    items = load_approval_queue()
    deleted_item = None
    for item in items:
        if item.get("id") == approval_id:
            deleted_item = item
            break

    if deleted_item:
        items = [item for item in items if item.get("id") != approval_id]
        with open(APPROVAL_QUEUE_FILE, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return True, deleted_item
    return False, None


def get_approval_item(approval_id: str) -> dict | None:
    """获取单个审批项"""
    items = load_approval_queue()
    for item in items:
        if item.get("id") == approval_id:
            return item
    return None


def get_approval_stats() -> dict:
    """获取审批统计"""
    items = load_approval_queue()
    return {
        "total": len(items),
        "pending": sum(1 for item in items if item.get("status") == "pending"),
        "approved": sum(1 for item in items if item.get("status") == "approved"),
        "rejected": sum(1 for item in items if item.get("status") == "rejected"),
    }