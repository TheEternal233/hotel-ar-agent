"""酒店应收会计AI智能体 — FastAPI Web服务 + 静态前端 + 专用模块端点"""
import asyncio
import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from deps import FRONTEND_DIR, logger

from routers import chat, ota, aging, card, ctrip, invoice, config, scheduler, files, audit as audit_router
from utils.audit_engine import audit as _audit_logger


async def _audit_cleanup_daemon():
    """后台定时清理审计日志：每天凌晨 3 点删除 7 天前的记录。"""
    while True:
        now = time.localtime()
        # 计算到凌晨 3 点的秒数
        seconds_until_3am = (3 - now.tm_hour) * 3600 - now.tm_min * 60 - now.tm_sec
        if seconds_until_3am <= 0:
            seconds_until_3am += 86400  # 已经过了 3 点，等明天
        await asyncio.sleep(seconds_until_3am)

        try:
            deleted = _audit_logger.cleanup(retain_days=7)
            if deleted > 0:
                logger.info(f"审计日志自动清理: 删除 {deleted} 个超过 7 天的文件")
        except Exception as e:
            logger.warning(f"审计日志自动清理失败: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("酒店应收会计AI智能体服务启动 http://127.0.0.1:8000")
    cleanup_task = asyncio.create_task(_audit_cleanup_daemon())
    yield
    cleanup_task.cancel()
    logger.info("服务关闭")


app = FastAPI(title="酒店应收会计AI智能体系统", version="2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


# ── 审计中间件：自动记录关键 API 请求 ──
@app.middleware("http")
async def audit_middleware(request: Request, call_next):
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
        method = request.method

        should_log = False

        # 1. 所有写操作都记录
        if method in ("POST", "PUT", "DELETE"):
            # 但跳过文件上传验证、审计日志自身、前端静态资源
            if not path.startswith("/api/audit/") and not path.startswith("/frontend"):
                should_log = True

        # 2. 特定的 GET 操作需要记录（AI对话、OTA对账、信用卡对账）
        elif method == "GET":
            if path.startswith("/api/chat") or path.startswith("/api/ota") or path.startswith("/api/card"):
                should_log = True

        if should_log:
            audit_status = "success" if status_code < 400 else "failed"
            client_ip = request.client.host if request.client else ""

            _audit_logger.log(
                module="api",
                action=method.lower(),
                detail=f"{method} {path} → {status_code}",
                user="system",
                ip=client_ip,
                status=audit_status,
                context={"path": path, "method": method, "status_code": status_code},
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
app.include_router(audit_router.router)