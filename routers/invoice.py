from fastapi import APIRouter, HTTPException

from tools.invoice import invoice_gen
from deps import logger
from schemas import InvoiceRequest

router = APIRouter(prefix="/api", tags=["invoice"])


@router.post("/invoice/gen")
async def invoice_gen_endpoint(req: InvoiceRequest):
    try:
        result = invoice_gen.invoke({"receivable_path": req.receivable_path, "invoice_type": req.invoice_type})
        return {"ok": True, "result": str(result)}
    except Exception as e:
        logger.error(f"Invoice error: {e}")
        raise HTTPException(status_code=500, detail=str(e))