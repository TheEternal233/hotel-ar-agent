from fastapi import APIRouter, HTTPException

from tools.data_integration import data_integration
from deps import logger
from schemas import ConfigRequest

router = APIRouter(prefix="/api", tags=["config"])


@router.post("/config/{action}")
async def config_action(action: str, req: ConfigRequest = None):
    try:
        sp = req.source_path if req else ""
        result = data_integration.invoke({"action": action, "source_path": sp})
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Config {action} error: {e}")
        raise HTTPException(status_code=500, detail=str(e))