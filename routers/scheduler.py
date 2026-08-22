import os
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from orchestrator.task_engine import TaskEngine, TaskDef
from orchestrator.supervisor import ConfidenceAssessor
from orchestrator.approval_store import (
    load_approval_queue,
    save_approval_item,
    update_approval_item,
    delete_approval_item,
    get_approval_item,
    get_approval_stats,
)
from deps import BASE_DIR, UPLOAD_DIR, logger
from utils.audit_logger import audit

router = APIRouter(prefix="/api", tags=["scheduler"])


# ========== 请求模型 ==========
class ApprovalAction(BaseModel):
    approval_id: str
    action: str  # "approve" | "reject" | "add_note"
    note: Optional[str] = ""


# ========== 任务引擎构建 ==========
def _build_engine(mode: str) -> TaskEngine:
    """根据模式构建任务引擎"""

    engine = TaskEngine()

    if mode == "daily":
        # 日清：信用卡对账
        def _run_card():
            mod = __import__("tools.credit_card_recon.credit_card_recon", fromlist=["batch_card_recon"])
            return mod.batch_card_recon(os.path.join(BASE_DIR, "data", "清远", "信用卡对账"))
        engine.register(TaskDef(
            name="credit_card_recon",
            func=_run_card,
            required_paths=[os.path.join(BASE_DIR, "data", "清远", "信用卡对账")],
            priority=1,
        ))

    elif mode == "monthly":
        # 月度：OTA对账（扫描 uploads 目录，完成后清理源文件）
        ota_data_dir = str(UPLOAD_DIR)
        def _run_ota():
            mod = __import__("tools.ar_recon.batch_runner", fromlist=["batch_ota_recon"])
            return mod.batch_ota_recon(ota_data_dir, cleanup=True)
        engine.register(TaskDef(
            name="ota_recon",
            func=_run_ota,
            required_paths=[ota_data_dir],
            priority=1,
        ))

    return engine


# ========== API 路由 ==========
@router.post("/scheduler/{mode}")
async def scheduler_run(mode: str):
    if mode not in ("daily", "monthly"):
        raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")

    engine = _build_engine(mode)
    results = await engine.run()

    messages = []
    pending_approvals = []

    for r in results:
        status = "✅" if r.success else "❌"
        review_mark = " [待复核]" if r.needs_review else ""
        msg = f"[{r.name}] {status}{review_mark} {r.output if r.success else r.error} ({r.duration_ms}ms)"
        messages.append(msg)

        # 记录需要复核的任务到审批队列
        if r.needs_review:
            approval_item = {
                "id": f"AP_{datetime.now():%Y%m%d%H%M%S}_{r.name}",
                "task_name": r.name,
                "status": "pending",
                "confidence": r.confidence,
                "output": r.output if r.success else r.error,
                "created_at": datetime.now().isoformat(),
                "mode": mode,
            }
            save_approval_item(approval_item)
            pending_approvals.append(approval_item)

    summary = {
            "total": len(results),
            "success": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success),
            "needs_review": sum(1 for r in results if r.needs_review),
        }

    audit.log("scheduler", "start", f"智能调度执行完成: {summary['success']}/{summary['total']}成功",
              context={"mode": mode, "total": summary["total"], "success": summary["success"],
                       "failed": summary["failed"], "needs_review": summary["needs_review"]})

    return {
        "ok": True,
        "results": messages,
        "summary": summary,
        "pending_approvals": pending_approvals,
    }


@router.get("/scheduler/approvals")
async def get_approval_queue_endpoint(status: Optional[str] = None):
    """获取审批队列"""
    items = load_approval_queue()
    if status:
        items = [item for item in items if item.get("status") == status]
    return {"ok": True, "items": items}


def _extract_output_paths(output_text: str) -> list[str]:
    """从任务输出文本中提取生成的文件路径"""
    import re
    paths = []
    # 匹配常见的文件路径模式
    patterns = [
        r'报告[:：]\s*([A-Za-z]:\\[^\n]+)',
        r'输出[:：]\s*([A-Za-z]:\\[^\n]+)',
        r'文件[:：]\s*([A-Za-z]:\\[^\n]+)',
        r'([A-Za-z]:\\[^\n]+\\output[^\n]*\.xlsx)',
        r'([A-Za-z]:\\[^\n]+\.xlsx)',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, output_text)
        paths.extend(matches)
    return paths


def _handle_rejected_files(output_text: str):
    """处理被驳回/删除的文件：移动到 rejected 目录"""
    paths = _extract_output_paths(output_text)
    rejected_dir = os.path.join(BASE_DIR, "output", "_rejected")
    os.makedirs(rejected_dir, exist_ok=True)

    moved = []
    for path in paths:
        if os.path.exists(path):
            try:
                import shutil
                filename = os.path.basename(path)
                dest = os.path.join(rejected_dir, f"{datetime.now():%Y%m%d_%H%M%S}_{filename}")
                shutil.move(path, dest)
                moved.append(dest)
                logger.info(f"已驳回文件已移动: {path} -> {dest}")
            except Exception as e:
                logger.error(f"移动驳回文件失败 {path}: {e}")

    return moved


@router.post("/scheduler/approvals/{approval_id}/action")
async def approval_action(approval_id: str, action: ApprovalAction):
    """处理审批动作"""
    if action.approval_id != approval_id:
        raise HTTPException(status_code=400, detail="审批ID不匹配")

    valid_actions = {"approve", "reject", "add_note"}
    if action.action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"无效动作: {action.action}")

    # 如果是驳回，先获取审批项信息以便处理文件
    if action.action == "reject":
        item = get_approval_item(approval_id)
        if item:
            output_text = item.get("output", "")
            moved_files = _handle_rejected_files(output_text)
            logger.info(f"审批驳回，已处理文件: {moved_files}")

    updates = {
        "status": "approved" if action.action == "approve" else ("rejected" if action.action == "reject" else "pending"),
        "resolved_at": datetime.now().isoformat(),
        "note": action.note,
        "action": action.action,
    }

    if update_approval_item(approval_id, updates):
        audit.log("scheduler", updates["action"], f"审批{updates['status']}: {approval_id}",
                  context={"approval_id": approval_id, "action": action.action, "note": action.note})
        return {"ok": True, "message": f"审批已{updates['status']}"}
    else:
        raise HTTPException(status_code=404, detail="审批项不存在")


@router.delete("/scheduler/approvals/{approval_id}")
async def delete_approval(approval_id: str):
    """删除审批项（同时处理关联文件）"""
    # 先获取审批项信息
    item = get_approval_item(approval_id)

    success, deleted_item = delete_approval_item(approval_id)
    if success and deleted_item:
        # 删除关联的输出文件
        output_text = deleted_item.get("output", "")
        moved_files = _handle_rejected_files(output_text)
        logger.info(f"审批删除，已处理文件: {moved_files}")
        return {"ok": True, "message": "审批项已删除", "files_moved": moved_files}
    else:
        raise HTTPException(status_code=404, detail="审批项不存在")


@router.get("/scheduler/stats")
async def scheduler_stats():
    """获取调度统计信息"""
    stats = get_approval_stats()
    return {"ok": True, "stats": stats}