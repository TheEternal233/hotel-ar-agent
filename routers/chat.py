import json
import uuid

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from deps import get_graph, cleanup_uploads, UPLOAD_DIR, is_safe_path, logger
from schemas import ChatRequest, ChatResponse

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(req: ChatRequest):
    try:
        graph = get_graph()
        msg_content = req.message
        if req.uploaded_files:
            msg_content = "用户已上传以下文件：\n" + "\n".join(f"  - {f}" for f in req.uploaded_files) + "\n\n用户请求：" + req.message
        user_input = {"messages": [HumanMessage(content=msg_content)]}
        thread_id = req.thread_id or str(uuid.uuid4())
        cfg = {"configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(user_input, cfg)
        msgs = result.get("messages", [])

        cleanup_uploads(req.uploaded_files)
        return ChatResponse(
            response=msgs[-1].content if msgs else "",
            thread_id=thread_id,
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    async def sse_gen():
        graph = get_graph()
        msg_content = req.message
        if req.uploaded_files:
            msg_content = "用户已上传以下文件：\n" + "\n".join(f"  - {f}" for f in req.uploaded_files) + "\n\n用户请求：" + req.message
        user_input = {"messages": [HumanMessage(content=msg_content)]}
        cfg = {"configurable": {"thread_id": req.thread_id or str(uuid.uuid4())}}
        try:
            async for event in graph.astream_events(user_input, cfg, version="v2"):
                kind = event["event"]
                if kind == "on_chat_model_stream":
                    chunk = event["data"]["chunk"]
                    if hasattr(chunk, "content") and chunk.content:
                        yield f"data: {json.dumps({'type':'token','content':chunk.content}, ensure_ascii=False)}\n\n"
                elif kind == "on_tool_start":
                    yield f"data: {json.dumps({'type':'tool_start','name':event.get('name','')})}\n\n"
                elif kind == "on_tool_end":
                    yield f"data: {json.dumps({'type':'tool_end','name':event.get('name','')})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type':'error','content':str(e)}, ensure_ascii=False)}\n\n"
        cleanup_uploads(req.uploaded_files)
        yield "data: [DONE]\n\n"
    return StreamingResponse(sse_gen(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","Connection":"keep-alive","X-Accel-Buffering":"no"})


@router.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    UPLOAD_DIR.mkdir(exist_ok=True)
    file_path = (UPLOAD_DIR / file.filename).resolve()
    if not is_safe_path(file_path, UPLOAD_DIR):
        raise HTTPException(status_code=400, detail="非法文件名")
    with open(file_path, "wb") as f:
        f.write(await file.read())
    return {"filename": file.filename, "path": str(file_path), "size": file_path.stat().st_size}