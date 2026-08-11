from fastapi import APIRouter, HTTPException

from tools.ctrip_commission_reconcile.ctrip_commission import ctrip_commission
from deps import logger
from schemas import CtripRequest

router = APIRouter(prefix="/api", tags=["ctrip"])


@router.post("/ctrip/commission")
async def ctrip_commission_endpoint(req: CtripRequest):
    try:
        result = ctrip_commission.invoke({
            "ctrip_filename": req.settlement_path,
            "pms_filename": req.pms_path,
        })
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Ctrip commission error: {e}")
        raise HTTPException(status_code=500, detail=str(e))