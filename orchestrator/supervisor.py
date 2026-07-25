from typing import Literal
from datetime import datetime
from state import AgentState

class ApprovalGate:
    @staticmethod
    def request_approval(state: AgentState, context: str) -> dict:
        state["pending_approval"] = {"id": f"AP_{datetime.now():%Y%m%d%H%M%S}", "context": context, "status": "pending", "timestamp": datetime.now().isoformat()}
        from langgraph.types import interrupt
        return {"pending_approval": state["pending_approval"], "approval_result": interrupt(f"[confirm] {context}")}

class TaskScheduler:
    SCHEDULE = {"daily": ["daily_check","daily_ar","credit_card_recon"], "monthly": ["ota_recon","aging_analysis","ctrip_commission"], "weekly": ["credit_card_recon"]}
    @staticmethod
    def get_tasks(mode="daily") -> list:
        if mode == "all": return list(set(t for v in TaskScheduler.SCHEDULE.values() for t in v))
        return TaskScheduler.SCHEDULE.get(mode, [])
