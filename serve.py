"""酒店应收会计AI智能体 — FastAPI Web服务 + 静态前端 + 专用模块端点"""
import json, os, logging, uuid
import shutil
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from requests.packages import target
from starlette.responses import FileResponse

from graph import build_graph

# 直接导入工具函数，绕开LLM直接调用
from tools.ar_recon import ar_recon
from tools.protocol_settlement.aging_pms import aging_analysis, aging_and_notice
from tools.ctrip_commission_reconcile.ctrip_commission import ctrip_commission
from tools.credit_card_recon import credit_card_recon
from tools.data_integration import data_integration

from tools.invoice import invoice_gen
from tools.night_audit import daily_check_handler

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_graph = None
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"

def _ensure_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph

def _cleanup_uploads(file_paths: list[str]):
    """AI处理完成后，清理 uploads 目录下的上传文件"""
    for p in file_paths:
        try:
            fp=Path(p)
            if fp.exists() and UPLOAD_DIR in fp.parents:
                fp.unlink()
        except OSError:
            pass

def _is_safe_path(target: Path, base: Path) -> bool:
    """安全检查：target 必须位于 base 目录下"""
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except (OSError, ValueError):
        return False


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
    pms_path: str = ""

class InvoiceRequest(BaseModel):
    receivable_path: str
    invoice_type: str = "普通发票"

class CorpReconRequest(BaseModel):
    receivable_path: str

class ConfigRequest(BaseModel):
    action: str
    source_path: str = ""

class AgingNoticeRequest(BaseModel):
    receivable_path: str
    as_of_date: str = ""
    notice_month: str = ""
    notice_date: str = ""
    due_date: str = ""

class DailyCheckRequest(BaseModel):
    ota_paths: list[str] = []
    card_paths: list[str] = []


class FileListResponse(BaseModel):
    ok:bool
    files: list=[]
    detail: str=""

class FileDeleteRequest(BaseModel):
    path: str


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

        # 清理uploads下的上传文件
        _cleanup_uploads(req.uploaded_files)
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
        # AI处理完成后，清理uploads下的上传文件
        _cleanup_uploads(req.uploaded_files)
        yield "data: [DONE]\n\n"
    return StreamingResponse(sse_gen(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","Connection":"keep-alive","X-Accel-Buffering":"no"})


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    UPLOAD_DIR.mkdir(exist_ok=True)
    file_path = (UPLOAD_DIR / file.filename).resolve()
    if not _is_safe_path(file_path,UPLOAD_DIR):
        raise HTTPException(status_code=400,detail="非法文件名")
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
    """账龄分析 + 付款通知书联合生成（前端无感知）"""
    try:
        # 从截止日期推断账期月份，如 2026-07-31 -> 2026-07
        notice_month = req.as_of_date[:7] if req.as_of_date else ""

        result = aging_and_notice.invoke({
            "receivable_path": req.receivable_path,
            "as_of_date": req.as_of_date,
            "notice_month": notice_month,
        })
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Aging+Notice error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/daily/check")
async def daily_check(req: DailyCheckRequest):
    """每日核对工作台：汇总 OTA 和信用卡对账结果"""
    try:
        result = daily_check_handler(req.ota_paths, req.card_paths)
        return {"ok": True, "result": str(result)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Daily check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/card/recon")
async def card_recon(req: CardReconRequest):
    """信用卡对账：直接调用 credit_card_recon 工具"""
    try:
        result = credit_card_recon.invoke({"bank_statement_path": req.bank_statement_path, "pms_card_path": req.pms_card_path})
        _cleanup_uploads([req.bank_statement_path, req.pms_card_path])
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Card recon error: {e}")
        _cleanup_uploads([req.bank_statement_path, req.pms_card_path])
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/ctrip/commission")
async def ctrip_commission_endpoint(req: CtripRequest):
    """携程佣金：直接调用 ctrip_commission 工具"""
    try:
        result = ctrip_commission.invoke({
            "ctrip_filename": req.settlement_path,
            "pms_filename": req.pms_path,
        })
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
                pms_files = [f for f in upload_map if "pms" in f.lower()]
                r = ctrip_commission.invoke({
                    "ctrip_filename": upload_map[ctrip_files[0]],
                    "pms_filename": upload_map[pms_files[0]] if pms_files else "",
                })
                results.append(f"[携程佣金] {r}")
            if not results:
                results.append("uploads目录下未找到匹配文件，请先上传数据文件")

        else:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")

        return {"ok": True, "results": results}
    except Exception as e:
        logger.error(f"Scheduler {mode} error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/aging/notice")
async def aging_notice(req: AgingNoticeRequest):
    """账龄分析 + 付款通知书联合生成"""
    try:
        result = aging_and_notice.invoke({
            "receivable_path": req.receivable_path,
            "as_of_date": req.as_of_date,
            "notice_month": req.notice_month,
            "notice_date": req.notice_date,
            "due_date": req.due_date,
        })
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Aging+Notice error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/files")
async def list_files(dir_type: str, sub_path: str = ""):
    """列出uploads或output下的文件和文件夹"""
    if dir_type == "uploads":
        base_dir = UPLOAD_DIR
    elif dir_type == "output":
        base_dir = OUTPUT_DIR
    else:
        raise HTTPException(status_code=400, detail="dir_type必须是uploads或output")

    target_dir = base_dir / sub_path if sub_path else base_dir
    if not target_dir.exists():
        return {"ok": True, "files": [], "current_path": sub_path}

    # 安全检查
    if not _is_safe_path(target_dir.resolve(), base_dir):
        raise HTTPException(status_code=403, detail="路径越界")

    items = []
    for f in sorted(target_dir.iterdir(), key=lambda x: (not x.is_dir(), x.stat().st_mtime), reverse=False):
        stat = f.stat()
        item = {
            "name": f.name,
            "path": str(f),
            "is_dir": f.is_dir(),
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }
        if f.is_dir():
            item["open_url"] = f"/api/files?dir_type={dir_type}&sub_path={sub_path + '/' + f.name if sub_path else f.name}"
        else:
            item["size"] = stat.st_size
            item["download_url"] = f"/api/download?path={str(f)}"
        items.append(item)

    return {"ok": True, "files": items, "current_path": sub_path}



@app.post("/api/files/delete")
async def delete_file(req: FileDeleteRequest):
    """删除uploads或output下的指定文件或文件夹"""
    try:
        fp=Path(req.path).resolve()
        if not (_is_safe_path(fp,UPLOAD_DIR) or _is_safe_path(fp,OUTPUT_DIR)):
            raise HTTPException(status_code=403,detail="只能删除uploads或output目录下的文件")
        if not fp.exists():
            raise HTTPException(status_code=404,detail="文件或文件夹不存在")

        if fp.is_dir():
            shutil.rmtree(fp)
        else:
            fp.unlink()
        return {"ok": True,"message":f"已删除: {fp.name}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete file error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/files/cleanup")
async def cleanup_directory(req:dict):
    """清空指定目录uploads或output"""
    dir_type=req.get("dir_type","")
    sub_path=req.get("sub_path","")
    if dir_type == "uploads":
        base_dir=UPLOAD_DIR
    elif dir_type == "output":
        base_dir=OUTPUT_DIR
    else:
        raise HTTPException(status_code=400,detail="dir_type必须是uploads或output")

    target_dir = base_dir / sub_path if sub_path else base_dir
    if not _is_safe_path(target_dir.resolve(), base_dir):
        raise HTTPException(status_code=403,detail="路径越界")

    deleted=0
    for f in target_dir.iterdir():
            try:
                if f.is_dir():
                    shutil.rmtree(f)
                else:
                    f.unlink()
                deleted+=1
            except OSError:
                pass

    return {"ok":True, "message":f"已清理{deleted}个文件或文件夹"}


@app.get("/api/download")
async def download_file(path: str):
    fp = Path(path).resolve()
    if not (_is_safe_path(fp, UPLOAD_DIR) or _is_safe_path(fp, OUTPUT_DIR)):
        raise HTTPException(status_code=403, detail="...")
    if not fp.exists():
        raise HTTPException(status_code=404, detail="...")
    return FileResponse(path=fp, filename=fp.name, media_type="application/octet-stream")
