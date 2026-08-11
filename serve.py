"""酒店应收会计AI智能体 — FastAPI Web服务 + 静态前端 + 专用模块端点"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from deps import FRONTEND_DIR, logger

from routers import chat, ota, aging, card, ctrip, invoice, config, scheduler, files


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("酒店应收会计AI智能体服务启动 http://127.0.0.1:8000")
    yield
    logger.info("服务关闭")


app = FastAPI(title="酒店应收会计AI智能体系统", version="2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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