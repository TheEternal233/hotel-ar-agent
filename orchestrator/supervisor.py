from typing import Literal
from datetime import datetime
from state import AgentState, TaskResultInfo

class ConfidenceAssessor:
    """置信度评估器：根据任务执行结果计算置信度分数"""

    @staticmethod
    def assess(result: dict) -> float:
        """
        评估任务结果的置信度，返回 0.0 ~ 1.0 的分数
        """
        # 1. 任务执行失败 -> 置信度为 0
        if not result.get("success", False):
            return 0.0

        output = result.get("output", "")
        error = result.get("error", "")

        # 2. 输出中包含错误关键词 -> 降低置信度
        error_keywords = ["错误", "失败", "异常", "不匹配", "差异", "❌"]
        if any(kw in output for kw in error_keywords) or any(kw in error for kw in error_keywords):
            return 0.3

        # 3. 输出中包含警告/差异 -> 中等置信度
        warning_keywords = ["差异", "未匹配", "跳过", "⚠️", "警告"]
        if any(kw in output for kw in warning_keywords):
            return 0.6

        # 4. 完全成功且无异常 -> 高置信度
        success_keywords = ["成功", "完成", "✅", "对平"]
        if any(kw in output for kw in success_keywords):
            return 1.0

        # 默认中等置信度
        return 0.7

    @staticmethod
    def needs_human_review(confidence: float, threshold: float = 0.8) -> bool:
        """判断是否需要人工复核"""
        return confidence < threshold


class ApprovalGate:
    """审批门控：管理人工复核流程"""

    THRESHOLD = 0.8  # 置信度阈值，低于此值需要人工复核

    @staticmethod
    def request_approval(state: AgentState, context: str, task_name: str = "", confidence: float = 0.0, result_summary: str = "") -> dict:
        """请求人工审批，使用 LangGraph interrupt 机制"""
        approval_id = f"AP_{datetime.now():%Y%m%d%H%M%S}_{task_name}"
        state["pending_approval"] = {
            "id": approval_id,
            "context": context,
            "status": "pending",
            "timestamp": datetime.now().isoformat(),
            "task_name": task_name,
            "confidence": confidence,
            "result_summary": result_summary,
        }
        from langgraph.types import interrupt
        return {
            "pending_approval": state["pending_approval"],
            "approval_result": interrupt(f"[待审批] {context}\n\n任务: {task_name}\n置信度: {confidence:.0%}\n\n请确认是否通过？")
        }

    @staticmethod
    def process_approval_result(state: AgentState, result: str) -> dict:
        """处理审批结果"""
        approval = state.get("pending_approval", {})
        approval["status"] = "approved" if result.lower() in ("yes", "y", "通过", "确认", "approve") else "rejected"
        approval["resolved_at"] = datetime.now().isoformat()
        approval["resolution"] = result

        return {
            "pending_approval": approval,
            "approval_result": result,
            "messages": [{
                "role": "system",
                "content": f"审批结果: {'已通过' if approval['status'] == 'approved' else '已驳回'} - {result}"
            }]
        }


class TaskScheduler:
    SCHEDULE = {
        "daily": ["daily_check", "daily_ar", "credit_card_recon"],
        "monthly": ["ota_recon", "aging_analysis", "ctrip_commission"],
        "weekly": ["credit_card_recon"]
    }

    @staticmethod
    def get_tasks(mode="daily") -> list:
        if mode == "all":
            return list(set(t for v in TaskScheduler.SCHEDULE.values() for t in v))
        return TaskScheduler.SCHEDULE.get(mode, [])