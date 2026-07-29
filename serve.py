"""酒店应收会计AI智能体 — FastAPI Web服务 + 静态前端 + 专用模块端点"""
import json, os, logging, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from graph import build_graph

# 直接导入工具函数，绕开LLM直接调用
from tools.ar_recon import ar_recon
from tools.aging import aging_analysis
from tools.ctrip_commission import ctrip_commission
from tools.credit_card_recon import credit_card_recon
from tools.data_integration import data_integration
from tools.corp_recon import corp_recon
from tools.invoice import invoice_gen

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_graph = None
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"


def _ensure_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


# ── Pydantic Models ──
class ChatRequest(BaseModel):
    message: str
    thread_id: str = ""
    uploaded_files: list[str] = []

class ChatResponse(BaseModel):
    response: str
    thread_id: str = ""

class TaskRequest(BaseModel):
    module: str
    file_paths: list[str] = []
    thread_id: str = ""

class OtaReconRequest(BaseModel):
    ota_path: str
    pms_path: str

class AgingRequest(BaseModel):
    receivable_path: str
    as_of_date: str = ""

class CardReconRequest(BaseModel):
    bank_statement_path: str
    pms_card_path: str

class CtripRequest(BaseModel):
    settlement_path: str

class InvoiceRequest(BaseModel):
    receivable_path: str
    invoice_type: str = "普通发票"

class CorpReconRequest(BaseModel):
    receivable_path: str

class ConfigRequest(BaseModel):
    action: str
    source_path: str = ""


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("酒店应收会计AI智能体服务启动 http://127.0.0.1:8000")
    yield
    logger.info("服务关闭")


app = FastAPI(title="酒店应收会计AI智能体系统", version="2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

FRONTEND_DIR = BASE_DIR / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


@app.get("/")
async def index():
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>酒店应收会计AI智能体系统</h1><p>前端页面开发中...</p>")


@app.get("/api/health")
async def health():
    return {"status": "ok", "model": "deepseek-v4-pro", "modules": [
        "M01_数据准备", "M02_OTA对账", "M03_账龄分析", "M04_携程佣金",
        "M05_信用卡对账", "M06_协议客户", "M07_发票管理", "M08_智能调度"
    ]}


# ── AI 对话（仅 AI 对话面板使用）──
@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        graph = _ensure_graph()
        msg_content = req.message
        if req.uploaded_files:
            msg_content = "用户已上传以下文件：\n" + "\n".join(f"  - {f}" for f in req.uploaded_files) + "\n\n用户请求：" + req.message
        user_input = {"messages": [HumanMessage(content=msg_content)]}
        thread_id = req.thread_id or str(uuid.uuid4())
        cfg = {"configurable": {"thread_id": thread_id}}
        result = await graph.ainvoke(user_input, cfg)
        msgs = result.get("messages", [])
        return ChatResponse(
            response=msgs[-1].content if msgs else "",
            thread_id=thread_id,
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/stream")
async def chat_stream(req: ChatRequest):
    async def sse_gen():
        graph = _ensure_graph()
        # 将上传文件路径注入消息
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
        yield "data: [DONE]\n\n"
    return StreamingResponse(sse_gen(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","Connection":"keep-alive","X-Accel-Buffering":"no"})


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    UPLOAD_DIR.mkdir(exist_ok=True)
    file_path = UPLOAD_DIR / file.filename
    with open(file_path, "wb") as f:
        f.write(await file.read())
    return {"filename": file.filename, "path": str(file_path), "size": file_path.stat().st_size}


# ══════════════════════════════════════════════════════════════════
# 专用模块端点 — 直接调用工具函数，不经过 LLM Agent
# ══════════════════════════════════════════════════════════════════

@app.post("/api/ota/recon")
async def ota_recon(req: OtaReconRequest):
    """OTA对账：直接调用 ar_recon 工具"""
    try:
        result = ar_recon.invoke({"ota_path": req.ota_path, "pms_path": req.pms_path})
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"OTA recon error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/aging/analyze")
async def aging_analyze(req: AgingRequest):
    """账龄分析：直接调用 aging_analysis 工具"""
    try:
        result = aging_analysis.invoke({"receivable_path": req.receivable_path, "as_of_date": req.as_of_date})
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Aging error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/card/recon")
async def card_recon(req: CardReconRequest):
    """信用卡对账：直接调用 credit_card_recon 工具"""
    try:
        result = credit_card_recon.invoke({"bank_statement_path": req.bank_statement_path, "pms_card_path": req.pms_card_path})
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Card recon error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ctrip/commission")
async def ctrip_commission_endpoint(req: CtripRequest):
    """携程佣金：直接调用 ctrip_commission 工具"""
    try:
        result = ctrip_commission.invoke({"settlement_path": req.settlement_path})
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Ctrip commission error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config/{action}")
async def config_action(action: str, req: ConfigRequest = None):
    """数据准备：直接调用 data_integration 工具"""
    try:
        sp = req.source_path if req else ""
        result = data_integration.invoke({"action": action, "source_path": sp})
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Config {action} error: {e}")
        raise HTTPException(status_code=500, detail=str(e))



@app.post("/api/invoice/gen")
async def invoice_gen_endpoint(req: InvoiceRequest):
    """发票管理：生成开票清单"""
    try:
        result = invoice_gen.invoke({"receivable_path": req.receivable_path, "invoice_type": req.invoice_type})
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/corp/recon")
async def corp_recon_endpoint(req: CorpReconRequest):
    """协议客户对账"""
    try:
        result = corp_recon.invoke({"receivable_path": req.receivable_path})
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Corp recon error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/batch/ota")
async def batch_ota():
    """批量OTA对账"""
    try:
        from tools.ar_recon import batch_ota_recon
        result = batch_ota_recon()
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Batch OTA error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/batch/card")
async def batch_card():
    """批量信用卡对账"""
    try:
        from tools.credit_card_recon import batch_card_recon
        result = batch_card_recon()
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Batch card error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/scheduler/{mode}")
async def scheduler_run(mode: str):
    """智能调度：串联多个工具执行批处理"""
    results = []
    try:
        if mode == "daily":
            from tools.credit_card_recon import batch_card_recon
            r = batch_card_recon(os.path.join(BASE_DIR, "data", "清远", "信用卡对账"))
            results.append(f"[信用卡对账] {r}")
            if not results:
                results.append("未找到数据文件")

        elif mode == "monthly":
            uploads = list(UPLOAD_DIR.glob("*.xlsx")) if UPLOAD_DIR.exists() else []
            upload_map = {f.name: str(f) for f in uploads}

            ota_file = upload_map.get("AR审核_OTA.xlsx", "")
            pms_file = upload_map.get("AR审核_PMS.xlsx", "")
            aging_file = upload_map.get("应收账龄分析表.xlsx", "")

            from tools.ar_recon import batch_ota_recon
            r = batch_ota_recon(os.path.join(BASE_DIR, "data", "清远", "OTA对账"))
            results.append(f"[OTA对账] {r}")
            if aging_file:
                r = aging_analysis.invoke({"receivable_path": aging_file, "as_of_date": ""})
                results.append(f"[账龄分析] {r}")
            # 携程佣金需要单独的结算单
            ctrip_files = [f for f in upload_map if "携程" in f or "ctrip" in f.lower()]
            if ctrip_files:
                r = ctrip_commission.invoke({"settlement_path": upload_map[ctrip_files[0]]})
                results.append(f"[携程佣金] {r}")
            if not results:
                results.append("uploads目录下未找到匹配文件，请先上传数据文件")

        else:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")

        return {"ok": True, "results": results}
    except Exception as e:
        logger.error(f"Scheduler {mode} error: {e}")
        raise HTTPException(status_code=500, detail=str(e))