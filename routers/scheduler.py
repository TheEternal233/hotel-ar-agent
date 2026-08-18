import os

from fastapi import APIRouter, HTTPException

from orchestrator.task_engine import TaskEngine, TaskDef
from deps import BASE_DIR, UPLOAD_DIR, logger

router = APIRouter(prefix="/api", tags=["scheduler"])



def _build_engine(mode: str) -> TaskEngine:
    """根据模式构建任务引擎"""

    engine = TaskEngine()

    if mode == "daily":
        # 日清：信用卡对账
        def _run_card():
            mod = __import__("tools.credit_card_recon.credit_card_recon", fromlist=["batch_card_recon"])
            return mod.batch_card_recon(os.path.join(BASE_DIR, "data", "清远", "信用卡对账"))
        engine.register(TaskDef(
            name="credit_card_recon",
            func=_run_card,
            required_paths=[os.path.join(BASE_DIR, "data", "清远", "信用卡对账")],
            priority=1,
        ))

    elif mode == "monthly":
        # 月度：OTA对账（扫描 uploads 目录，完成后清理源文件）
        ota_data_dir = str(UPLOAD_DIR)
        def _run_ota():
            mod = __import__("tools.ar_recon.batch_runner", fromlist=["batch_ota_recon"])
            return mod.batch_ota_recon(ota_data_dir, cleanup=True)
        engine.register(TaskDef(
            name="ota_recon",
            func=_run_ota,
            required_paths=[ota_data_dir],
            priority=1,
        ))

    return engine

@router.post("/scheduler/{mode}")
async def scheduler_run(mode: str):
    if mode not in ("daily", "monthly"):
        raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")

    engine = _build_engine(mode)
    results = await engine.run()

    messages = []
    for r in results:
        status = "✅" if r.success else "❌"
        msg = f"[{r.name}] {status} {r.output if r.success else r.error} ({r.duration_ms}ms)"
        messages.append(msg)

    return {
        "ok": True,
        "results": messages,
        "summary": {
            "total": len(results),
            "success": sum(1 for r in results if r.success),
            "failed": sum(1 for r in results if not r.success),
        }
    }