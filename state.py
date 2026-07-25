from typing import TypedDict, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

class ApprovalInfo(TypedDict, total=False):
    id: str; context: str; status: str; timestamp: str

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    mode: str; pending_tasks: list[str]; completed_tasks: list[str]
    pending_approval: ApprovalInfo; approval_result: str
    current_module: str; last_output_path: str; errors: list[str]
