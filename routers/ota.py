from fastapi import APIRouter, HTTPException

from tools.ar_recon import ar_recon
from deps import logger
from schemas import OtaReconRequest

router = APIRouter(prefix="/api", tags=["ota"])


@router.post("/ota/recon")
async def ota_recon(req: OtaReconRequest):
    try:
        result = ar_recon.invoke({"ota_path": req.ota_path, "pms_path": req.pms_path})
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"OTA recon error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch/ota")
async def batch_ota():
    try:
        from tools.ar_recon import batch_ota_recon
        result = batch_ota_recon()
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Batch OTA error: {e}")
        raise HTTPException(status_code=500, detail=str(e))