"""Hotel AR AI Agent - CLI
Usage:
    python main.py --serve      启动 web 服务
    python main.py --task "对账" --file xlsx 单次任务
    python main.py              交互式对话
"""
import argparse

from graph import build_graph
from langchain_core.messages import HumanMessage

def _print_banner():
    print("="*50)
    print("  Hotel AR AI Agent | quit=exit")
    print("="*50)

def _print_messages(messages,prefix=""):
    for msg in messages:
        if hasattr(msg,"content") and msg.content and msg.type!="tool":
            label=f"[{prefix}]" if prefix else ""
            print(f"{label}{msg.content}")

def _run_serve():
    import uvicorn
    uvicorn.run("serve:app",host="127.0.0.1",port=9000,reload=False)


def _run_oneshot(task:str,file_path:str):
    graph=build_graph()
    prompt=task
    if file_path:
        prompt+=f", path: {file_path}"

    result=graph.invoke(
        {"messages":[HumanMessage(content=prompt)]},
        {"configurable":{"thread_id":"oneshot"}},
    )
    _print_messages(result.get("messages",[]))


def _run_interactive():
    graph=build_graph()
    thread_id="cli"
    _print_banner()

    while True:
        try:
            user_input=input("\n> ").strip()
        except (EOFError,KeyboardInterrupt):
            print("\n再见! ")
            break

        if not user_input:
            continue
        if user_input.lower() in ("quit","exit","q"):
            break

        config={"configurable":{"thread_id":thread_id}}
        for event in graph.stream(
                {"messages":[HumanMessage(content=user_input)]},config
        ):
            for node_name,node_output in event.items():
                if node_output and "messages" in node_output:
                    _print_messages(node_output["messages"],prefix=node_name)



def main():
    parser=argparse.ArgumentParser(
        description="Hotel AR AI Agent - 酒店应收会计AI智能体",
    )
    parser.add_argument("--task",default="",help="单次任务描述")
    parser.add_argument("--file",default="",help="任务关联的文件路径")
    parser.add_argument("--serve",action="store_true",help="启动 web 服务")
    args=parser.parse_args()
    if args.serve:
        _run_serve()
    elif args.task:
        _run_oneshot(args.task,args.file)
    else:
        _run_interactive()

if __name__ == "__main__":
    main()