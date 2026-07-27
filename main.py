"""Hotel AR AI Agent - CLI
Usage: python main.py [--task TASK] [--file PATH] [--serve]
"""
import argparse
from graph import build_graph
from langchain_core.messages import HumanMessage

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--task", default="")
    p.add_argument("--file", default="")
    p.add_argument("--serve", action="store_true")
    args = p.parse_args()
    if args.serve:
        import uvicorn; uvicorn.run("serve:app", host="127.0.0.1", port=9000, reload=True)
    elif args.task:
        g = build_graph()
        prompt = args.task
        if args.file: prompt += f", path: {args.file}"
        r = g.invoke({"messages": [HumanMessage(content=prompt)]}, {"configurable": {"thread_id": "oneshot"}})
        for m in r.get("messages", []):
            if hasattr(m, "content") and m.content and m.type != "tool": print(m.content)
    else:
        g = build_graph(); tid = "cli"
        print("=" * 50); print("  Hotel AR AI Agent  |  quit=exit"); print("=" * 50)
        while True:
            try: ui = input("\n> ").strip()
            except: break
            if not ui: continue
            if ui.lower() in ("quit","exit","q"): break
            cfg = {"configurable": {"thread_id": tid}}
            for ev in g.stream({"messages": [HumanMessage(content=ui)]}, cfg):
                for nn, no in ev.items():
                    if no and "messages" in no:
                        for m in no["messages"]:
                            if hasattr(m,"content") and m.content and m.type != "tool":
                                print(f"[{nn}] {m.content}")

if __name__ == "__main__": main()