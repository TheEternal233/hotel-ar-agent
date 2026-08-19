from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from state import AgentState
from agent import agent, TOOLS
from checkpointer import JsonFileSaver
from orchestrator.supervisor import ConfidenceAssessor, ApprovalGate


def assessment_node(state: AgentState) -> dict:
    """置信度评估节点：评估任务结果，决定是否需要人工复核"""
    current_task = state.get("current_task_result", {})
    if not current_task:
        return {"messages": [{"role": "system", "content": "没有任务需要评估"}]}

    confidence = current_task.get("confidence", 0.0)
    task_name = current_task.get("name", "未知任务")
    output = current_task.get("output", "")
    error = current_task.get("error", "")

    if ConfidenceAssessor.needs_human_review(confidence):
        # 需要人工复核，触发 interrupt
        summary = output if output else error
        return ApprovalGate.request_approval(
            state,
            context=f"任务 [{task_name}] 需要人工复核",
            task_name=task_name,
            confidence=confidence,
            result_summary=summary[:200]
        )
    else:
        # 高置信度，自动通过
        return {
            "messages": [{
                "role": "system",
                "content": f"✅ 任务 [{task_name}] 置信度 {confidence:.0%}，自动通过"
            }],
            "approval_result": "auto_approved",
            "pending_approval": {
                "status": "auto_approved",
                "task_name": task_name,
                "confidence": confidence
            }
        }


def approval_response_node(state: AgentState) -> dict:
    """处理人工审批结果"""
    approval_result = state.get("approval_result", "")
    if approval_result == "auto_approved":
        return {}

    return ApprovalGate.process_approval_result(state, approval_result)


def route_after_assessment(state: AgentState) -> str:
    """根据评估结果路由到不同节点"""
    approval = state.get("pending_approval", {})
    status = approval.get("status", "")

    if status == "pending":
        # 等待人工审批，流程暂停
        return "__end__"
    elif status in ("approved", "auto_approved"):
        # 已通过，继续执行
        return "agent"
    elif status == "rejected":
        # 已驳回，记录错误并结束
        return "agent"
    else:
        return "agent"


def build_graph():
    builder = StateGraph(AgentState)

    # 添加节点
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_node("assessment", assessment_node)
    builder.add_node("approval_response", approval_response_node)

    # 定义边
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "assessment")

    # 评估后根据结果路由
    builder.add_conditional_edges(
        "assessment",
        route_after_assessment,
        {
            "agent": "agent",
            "__end__": END,
        }
    )

    builder.add_edge("approval_response", "agent")

    return builder.compile(
        checkpointer=JsonFileSaver(
            save_dir="./data/memory",
            max_cache_threads=50,
        )
    )