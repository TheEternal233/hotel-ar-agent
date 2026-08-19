import json
import uuid
import asyncio

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

from deps import get_graph, cleanup_uploads, UPLOAD_DIR, is_safe_path, logger
from schemas import ChatRequest, ChatResponse
from orchestrator.approval_store import create_approval_item
from orchestrator.supervisor import ConfidenceAssessor

router = APIRouter(prefix="/api", tags=["chat"])


# ========== 重试装饰器 ==========
def retry_async(max_retries=2, delay=1):
    """简单的异步重试装饰器"""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    logger.warning(f"AI调用第{attempt + 1}次失败: {e}")
                    if attempt < max_retries:
                        await asyncio.sleep(delay * (attempt + 1))
            raise last_error
        return wrapper
    return decorator


def _assess_chat_result(response_text: str, tools_used: list[str]) -> tuple[float, bool]:
    """
    评估 AI 对话结果的置信度
    返回: (confidence, needs_review)
    """
    # 如果使用了工具（如对账、分析等），需要评估
    if not tools_used:
        # 纯对话，不涉及数据处理，高置信度
        return 1.0, False

    # 基于响应内容评估
    confidence = ConfidenceAssessor.assess({
        "success": True,
        "output": response_text,
        "error": ""
    })

    needs_review = ConfidenceAssessor.needs_human_review(confidence)
    return confidence, needs_review


def _extract_tools_used(messages: list) -> list[str]:
    """从消息中提取使用的工具名称"""
    tools = []
    for msg in messages:
        if hasattr(msg, 'tool_calls') and msg.tool_calls:
            for tc in msg.tool_calls:
                if hasattr(tc, 'name'):
                    tools.append(tc.name)
    return tools


# ========== 普通对话（带超时+重试） ==========
@retry_async(max_retries=2, delay=1)
async def _invoke_with_timeout(graph, user_input, cfg, timeout=60):
    """带60秒超时的 AI 调用"""
    return await asyncio.wait_for(
        graph.ainvoke(user_input, cfg),
        timeout=timeout
    )

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

        # 带超时+重试调用
        result = await _invoke_with_timeout(graph, user_input, cfg, timeout=60)
        msgs = result.get("messages", [])

        # 提取 AI 的最终回复
        response_text = msgs[-1].content if msgs else ""

        # 检测是否使用了工具
        tools_used = _extract_tools_used(msgs)

        # 评估置信度
        confidence, needs_review = _assess_chat_result(response_text, tools_used)

        # 如果需要复核，加入审批队列，并阻断结果输出
        approval_info = None
        if needs_review and tools_used:
            task_name = tools_used[0] if tools_used else "ai_task"
            approval_info = create_approval_item(
                task_name=task_name,
                confidence=confidence,
                output=response_text[:500],
                mode="ai_chat"
            )
            logger.info(f"AI对话结果已加入审批队列: {approval_info['id']}, 置信度: {confidence}")

            # 阻断低置信度结果的直接输出，只返回审批提示
            blocked_message = (
                f"⚠️ 该任务结果置信度较低（{confidence:.0%}），已提交人工复核。\n\n"
                f"审批ID: {approval_info['id']}\n"
                f"任务: {task_name}\n\n"
                f"请前往「智能调度」→「查看审批」进行复核。\n"
                f"复核通过后，结果将正式生效。"
            )
            cleanup_uploads(req.uploaded_files)
            return ChatResponse(
                response=blocked_message,
                thread_id=thread_id,
                needs_review=True,
                confidence=confidence,
                approval_id=approval_info["id"],
            )

        cleanup_uploads(req.uploaded_files)
        return ChatResponse(
            response=response_text,
            thread_id=thread_id,
            needs_review=False,
            confidence=confidence,
            approval_id=None,
        )
    except asyncio.TimeoutError:
        logger.error("AI调用超时")
        cleanup_uploads(req.uploaded_files)
        raise HTTPException(status_code=504, detail="AI响应超时，请稍后重试")
    except Exception as e:
        logger.error(f"Chat error: {e}")
        cleanup_uploads(req.uploaded_files)
        raise HTTPException(status_code=500, detail=f"AI服务异常: {str(e)}")

# ========== 流式对话（带超时） ==========
@router.post("/chat/stream")
async def chat_stream(req: ChatRequest):
    # 收集流式输出的完整内容
    stream_content = []
    tools_used = []

    async def sse_gen():
        graph = get_graph()
        msg_content = req.message
        if req.uploaded_files:
            msg_content = "用户已上传以下文件：\n" + "\n".join(f"  - {f}" for f in req.uploaded_files) + "\n\n用户请求：" + req.message
        user_input = {"messages": [HumanMessage(content=msg_content)]}
        cfg = {"configurable": {"thread_id": req.thread_id or str(uuid.uuid4())}}

        try:
            # 流式也加超时控制（整体超时120秒）
            async with asyncio.timeout(120):
                async for event in graph.astream_events(user_input, cfg, version="v2"):
                    kind = event["event"]
                    if kind == "on_chat_model_stream":
                        chunk = event["data"]["chunk"]
                        if hasattr(chunk, "content") and chunk.content:
                            stream_content.append(chunk.content)
                            yield f"data: {json.dumps({'type':'token','content':chunk.content}, ensure_ascii=False)}\n\n"
                    elif kind == "on_tool_start":
                        tool_name = event.get('name', '')
                        if tool_name:
                            tools_used.append(tool_name)
                        yield f"data: {json.dumps({'type':'tool_start','name':tool_name})}\n\n"
                    elif kind == "on_tool_end":
                        yield f"data: {json.dumps({'type':'tool_end','name':event.get('name','')})}\n\n"

        except asyncio.TimeoutError:
            logger.error("AI流式调用超时")
            yield f"data: {json.dumps({'type':'error','content':'AI响应超时，请稍后重试'}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
            yield f"data: {json.dumps({'type':'error','content':str(e)}, ensure_ascii=False)}\n\n"

        # 流式结束后，评估结果并可能加入审批队列
        full_response = "".join(stream_content)
        if tools_used:
            confidence, needs_review = _assess_chat_result(full_response, tools_used)
            if needs_review:
                task_name = tools_used[0]
                approval_info = create_approval_item(
                    task_name=task_name,
                    confidence=confidence,
                    output=full_response[:500],
                    mode="ai_chat"
                )
                logger.info(f"AI流式对话结果已加入审批队列: {approval_info['id']}")
                # 发送阻断指令给前端，让前端清空已显示内容并显示审批提示
                yield f"data: {json.dumps({'type':'approval_needed','approval_id':approval_info['id'],'confidence':confidence,'task_name':task_name}, ensure_ascii=False)}\n\n"
                cleanup_uploads(req.uploaded_files)
                yield "data: [DONE]\n\n"
                return

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