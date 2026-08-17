from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode, tools_condition
from state import AgentState
from agent import agent, TOOLS
from checkpointer import JsonFileSaver


def build_graph():
    builder = StateGraph(AgentState)
    builder.add_node("agent", agent)
    builder.add_node("tools", ToolNode(TOOLS))
    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", tools_condition)
    builder.add_edge("tools", "agent")
    return builder.compile(
        checkpointer=JsonFileSaver(
            save_dir="./data/memory",
            max_cache_threads=50,
        )
    )