"""酒店应收会计AI智能体 — FastAPI Web服务 + 静态前端 + 专用模块端点"""
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from deps import FRONTEND_DIR, logger

from routers import chat, ota, aging, card, ctrip, invoice, config, scheduler, files, audit


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("酒店应收会计AI智能体服务启动 http://127.0.0.1:8000")
    yield
    logger.info("服务关闭")


app = FastAPI(title="酒店应收会计AI智能体系统", version="2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── 审计中间件：自动记录所有 API 请求 ──
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
    from utils.audit_logger import audit as audit_logger

    start = time.perf_counter()
    response = None
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
    except Exception:
        status_code = 500
        raise
    finally:
        duration_ms = int((time.perf_counter() - start) * 1000)
        path = request.url.path

        # 跳过审计日志自身的查询接口，避免无限递归
        if path.startswith("/api/audit/") or path.startswith("/frontend"):
            pass
        elif path in ("/", "/api/health"):
            pass
        else:
            audit_status = "success" if status_code < 400 else "failed"
            client_ip = request.client.host if request.client else ""

            audit_logger.log(
                module="api",
                action=request.method.lower(),
                detail=f"{request.method} {path} → {status_code}",
                user="system",
                ip=client_ip,
                status=audit_status,
                context={"path": path, "method": request.method, "status_code": status_code},
                duration_ms=duration_ms,
            )

    return response


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


app.include_router(chat.router)
app.include_router(ota.router)
app.include_router(aging.router)
app.include_router(card.router)
app.include_router(ctrip.router)
app.include_router(invoice.router)
app.include_router(config.router)
app.include_router(scheduler.router)
app.include_router(files.router)
app.include_router(audit.router)