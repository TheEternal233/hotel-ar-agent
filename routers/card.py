from fastapi import APIRouter, HTTPException

from tools.credit_card_recon import credit_card_recon
from deps import cleanup_uploads, logger
from schemas import CardReconRequest

router = APIRouter(prefix="/api", tags=["card"])


@router.post("/card/recon")
async def card_recon(req: CardReconRequest):
    try:
        result = credit_card_recon.invoke({"bank_statement_path": req.bank_statement_path, "pms_card_path": req.pms_card_path})
        cleanup_uploads([req.bank_statement_path, req.pms_card_path])
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Card recon error: {e}")
        cleanup_uploads([req.bank_statement_path, req.pms_card_path])
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/batch/card")
async def batch_card():
    try:
        from tools.credit_card_recon import batch_card_recon
        result = batch_card_recon()
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Batch card error: {e}")
        raise HTTPException(status_code=500, detail=str(e))