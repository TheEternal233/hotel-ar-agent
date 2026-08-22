import os

from fastapi import APIRouter, HTTPException

from tools.credit_card_recon.constants import RECON_PAYMENT_METHODS
from tools.credit_card_recon.matcher import _reconcile_channel
from tools.credit_card_recon import credit_card_recon
from deps import cleanup_uploads, logger
from schemas import CardReconRequest, CardReconConfirmRequest
from tools.credit_card_recon.parser import _read_yfd_pms, _read_yfd_bank, _read_pos_statement, _read_pms_report
from tools.credit_card_recon.reporter import _generate_recon_report
from utils.audit_logger import audit

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



@router.post("/card/recon_preview")
async def card_recon_preview(req: CardReconRequest):
    """对账预览：返回结构化对账明细，供前端展示审核"""
    try:
        bank_path = req.bank_statement_path
        pms_path = req.pms_card_path
        for p in (bank_path, pms_path):
            if not p or not os.path.exists(p):
                raise HTTPException(status_code=400, detail=f"文件不存在: {p}")

        bank_lower = bank_path.lower()
        pms_lower = pms_path.lower()

        recon_results = []
        if "yfd" in bank_lower and "alipay" in bank_lower and "yfd" in pms_lower and "alipay" in pms_lower:
            pms_txs = _read_yfd_pms(pms_path, "YFD 支付宝")
            bank_txs = _read_yfd_bank(bank_path)
            recon_results.append(_reconcile_channel("YFD支付宝", pms_txs, bank_txs))
        elif "yfd" in bank_lower and "wechat" in bank_lower and "yfd" in pms_lower and "wechat" in pms_lower:
            pms_txs = _read_yfd_pms(pms_path, "YFD 微信")
            bank_txs = _read_yfd_bank(bank_path)
            recon_results.append(_reconcile_channel("YFD微信", pms_txs, bank_txs))
        else:
            pms_groups = _read_pms_report(pms_path)
            pos_groups = _read_pos_statement(bank_path)
            for method in RECON_PAYMENT_METHODS:
                pms_txs = pms_groups.get(method, [])
                pos_txs = pos_groups.get(method, [])
                if pms_txs or pos_txs:
                    recon_results.append(_reconcile_channel(method, pms_txs, pos_txs))

        summary = []
        unmatched_details = []
        for r in recon_results:
            flag = "对平" if r["balanced"] else "差异"
            summary.append({
                "channel": r["channel"],
                "pms_count": r["pms_count"],
                "bank_count": r["bank_count"],
                "count_match": r["count_match"],
                "pms_total": r["pms_total"],
                "bank_total": r["bank_total"],
                "diff": r["diff"],
                "amount_match": r["amount_match"],
                "all_matched": r.get("all_matched", True),
                "balanced": r["balanced"],
                "matched_count": r.get("matched_count", 0),
                "unmatched_pms_count": r.get("unmatched_pms_count", 0),
                "unmatched_bank_count": r.get("unmatched_bank_count", 0),
            })
            for um in r.get("unmatched_pms", []):
                unmatched_details.append({
                    "channel": r["channel"],
                    "source": "PMS",
                    "type": "PMS短款",
                    "amount": um.get("amount", 0),
                    "raw": um.get("raw", {}),
                    "id": f"pms_{r['channel']}_{um.get('amount', 0)}_{hash(str(um.get('raw', {}))) & 0xFFFFFFFF}",
                })
            for um in r.get("unmatched_bank", []):
                unmatched_details.append({
                    "channel": r["channel"],
                    "source": "POS",
                    "type": "POS长款",
                    "amount": um.get("amount", 0),
                    "raw": um.get("raw", {}),
                    "id": f"pos_{r['channel']}_{um.get('amount', 0)}_{hash(str(um.get('raw', {}))) & 0xFFFFFFFF}",
                })

        audit.log("card_recon", "preview", f"信用卡对账预览: {len(summary)}个渠道, 差异{sum(1 for s in summary if not s['balanced'])}个",
                  context={"summary": [{"channel": s["channel"], "balanced": s["balanced"], "diff": s["diff"]} for s in summary]})

        return {
            "ok": True,
            "summary": summary,
            "unmatched_details": unmatched_details,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Card recon preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/card/recon_confirm")
async def card_recon_confirm(req: CardReconConfirmRequest):
    """人工审核确认后生成对账报告。优先使用前端传入的recon_results，避免重复匹配"""
    try:
        bank_path = req.bank_statement_path
        pms_path = req.pms_card_path
        for p in (bank_path, pms_path):
            if not p or not os.path.exists(p):
                raise HTTPException(status_code=400, detail=f"文件不存在: {p}")

        # 优先使用前端传入的匹配结果，避免重复计算
        if req.recon_results:
            recon_results = req.recon_results
        else:
            # 兼容旧逻辑：前端未传入时重新执行匹配
            bank_lower = bank_path.lower()
            pms_lower = pms_path.lower()
            recon_results = []
            if "yfd" in bank_lower and "alipay" in bank_lower and "yfd" in pms_lower and "alipay" in pms_lower:
                pms_txs = _read_yfd_pms(pms_path, "YFD 支付宝")
                bank_txs = _read_yfd_bank(bank_path)
                recon_results.append(_reconcile_channel("YFD支付宝", pms_txs, bank_txs))
            elif "yfd" in bank_lower and "wechat" in bank_lower and "yfd" in pms_lower and "wechat" in pms_lower:
                pms_txs = _read_yfd_pms(pms_path, "YFD 微信")
                bank_txs = _read_yfd_bank(bank_path)
                recon_results.append(_reconcile_channel("YFD微信", pms_txs, bank_txs))
            else:
                pms_groups = _read_pms_report(pms_path)
                pos_groups = _read_pos_statement(bank_path)
                for method in RECON_PAYMENT_METHODS:
                    pms_txs = pms_groups.get(method, [])
                    pos_txs = pos_groups.get(method, [])
                    if pms_txs or pos_txs:
                        recon_results.append(_reconcile_channel(method, pms_txs, pos_txs))

        result_text = _generate_recon_report(recon_results)

        cleanup_uploads([bank_path, pms_path])

        audit.log("card_recon", "confirm", f"信用卡对账确认完成, 审核{len(req.review_items)}项",
                  context={"reviewed_count": len(req.review_items), "comments": req.comments})

        return {
            "ok": True,
            "result": result_text,
            "reviewed_count": len(req.review_items),
            "comments": req.comments,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Card recon confirm error: {e}")
        cleanup_uploads([req.bank_statement_path, req.pms_card_path])
        raise HTTPException(status_code=500, detail=str(e))