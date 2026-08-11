from fastapi import APIRouter, HTTPException

from tools.protocol_settlement.aging_pms import aging_and_notice
from deps import logger
from schemas import AgingRequest, AgingNoticeRequest

router = APIRouter(prefix="/api", tags=["aging"])


@router.post("/aging/analyze")
async def aging_analyze(req: AgingRequest):
    try:
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


@router.post("/aging/notice")
async def aging_notice(req: AgingNoticeRequest):
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