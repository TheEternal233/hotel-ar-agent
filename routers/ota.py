from fastapi import APIRouter, HTTPException

from tools.ar_recon import ar_recon, _match_ota_rezen_fnb, FNB_CHANNELS, match_xiangminiao, _match_ota_rezen
from deps import logger
from schemas import OtaReconRequest, OtaConfirmRequest, OtaMatchRequest, OtaUploadRequest
from tools.doc_parser import read_rezen, read_ota_channel, detect_ota_channel

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

@router.post("/ota/upload_preview")
async def ota_upload_preview(req: OtaUploadRequest):
    """Step 1: 上传文件后返回预览信息（行数、列名、检测到的渠道）"""
    try:
        import os
        result = {"ota": None, "pms": None}

        if req.ota_path and os.path.exists(req.ota_path):
            from tools.doc_parser import get_info
            ota_info = get_info(req.ota_path)
            channel = detect_ota_channel(req.ota_path)
            result["ota"] = {
                "filename": ota_info["filename"],
                "sheet": ota_info["sheet"],
                "rows": ota_info["rows"],
                "cols": ota_info["cols"],
                "headers": ota_info["headers"][:20],
                "detected_channel": channel,
            }

        if req.pms_path and os.path.exists(req.pms_path):
            from tools.doc_parser import get_info
            pms_info = get_info(req.pms_path)
            result["pms"] = {
                "filename": pms_info["filename"],
                "sheet": pms_info["sheet"],
                "rows": pms_info["rows"],
                "cols": pms_info["cols"],
                "headers": pms_info["headers"][:20],
                "is_rezen": any(m in " ".join(pms_info["headers"]) for m in ["账单号", "外部订单号"]),
            }

        return {"ok": True, "preview": result}
    except Exception as e:
        logger.error(f"OTA upload preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ota/match_preview")
async def ota_match_preview(req: OtaMatchRequest):
    """Step 2: 执行匹配，返回明细结果（匹配成功、差异、单边）"""
    try:
        import os
        if not os.path.exists(req.ota_path):
            raise HTTPException(status_code=400, detail=f"OTA文件不存在: {req.ota_path}")
        if not os.path.exists(req.pms_path):
            raise HTTPException(status_code=400, detail=f"PMS文件不存在: {req.pms_path}")

        channel = req.channel or detect_ota_channel(req.ota_path)
        if not channel or channel == "rezen":
            raise HTTPException(status_code=400, detail="无法自动检测渠道，请手动指定")

        if channel == "向蜜鸟":
            from utils.ar_recon_utils import read_xiangminiao
            ota_records, card_records, rezen_records = read_xiangminiao(req.ota_path)
            results, stats = match_xiangminiao(ota_records, rezen_records, card_records)
        elif channel in FNB_CHANNELS:
            ota_records = read_ota_channel(req.ota_path, channel)
            rezen_records = read_rezen(req.pms_path)
            results, stats = _match_ota_rezen_fnb(ota_records, rezen_records, channel)
        else:
            ota_records = read_ota_channel(req.ota_path, channel)
            rezen_records = read_rezen(req.pms_path)
            results, stats = _match_ota_rezen(ota_records, rezen_records, channel)

        # 格式化明细数据供前端展示
        match_list = []
        diff_list = []
        ota_only_list = []
        pms_only_list = []

        for idx, r in enumerate(results):
            item = {
                "id": idx,
                "status": r["status"],
                "ota_order": r.get("ota_order", ""),
                "pms_ext_order": r.get("pms_ext_order", ""),
                "ota_amount": r.get("ota_amount", 0),
                "pms_amount": r.get("pms_amount", 0),
                "diff": r.get("diff", 0),
            }
            if r["status"] == "match":
                match_list.append(item)
            elif r["status"] == "diff":
                item["ota_detail"] = r.get("ota", {})
                item["pms_detail"] = r.get("pms", {})
                diff_list.append(item)
            elif r["status"] == "ota_only":
                item["ota_detail"] = r.get("ota", {})
                ota_only_list.append(item)
            elif r["status"] == "pms_only":
                item["pms_detail"] = r.get("pms", {})
                pms_only_list.append(item)

        return {
            "ok": True,
            "channel": channel,
            "stats": stats,
            "details": {
                "match": match_list,
                "diff": diff_list,
                "ota_only": ota_only_list,
                "pms_only": pms_only_list,
            }
        }
    except Exception as e:
        logger.error(f"OTA match preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/ota/confirm")
async def ota_confirm(req: OtaConfirmRequest):
    """Step 3: 用户确认差异后，生成最终报告"""
    try:
        import os
        from tools.ar_recon.report_generator import _generate_ar_report_a, _generate_ar_report_fnb, _generate_ar_report
        from tools.ar_recon.constants import FNB_CHANNELS

        channel = req.channel or detect_ota_channel(req.ota_path)

        # 重新执行匹配获取完整结果
        if channel == "向蜜鸟":
            from utils.ar_recon_utils import read_xiangminiao
            ota_records, card_records, rezen_records = read_xiangminiao(req.ota_path)
            results, stats = match_xiangminiao(ota_records, rezen_records, card_records)
            report_path = _generate_ar_report(results, stats, channel, req.ota_path, req.pms_path)
        elif channel in FNB_CHANNELS:
            ota_records = read_ota_channel(req.ota_path, channel)
            rezen_records = read_rezen(req.pms_path)
            results, stats = _match_ota_rezen_fnb(ota_records, rezen_records, channel)
            report_path = _generate_ar_report_fnb(results, stats, channel, req.ota_path, req.pms_path)
        else:
            ota_records = read_ota_channel(req.ota_path, channel)
            rezen_records = read_rezen(req.pms_path)
            results, stats = _match_ota_rezen(ota_records, rezen_records, channel)
            report_path = _generate_ar_report_a(results, stats, channel, req.ota_path, req.pms_path)

        # 清理上传文件
        for p in (req.ota_path, req.pms_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

        return {
            "ok": True,
            "report_path": report_path,
            "stats": stats,
            "channel": channel,
            "confirmed": {
                "matches": len(req.confirmed_matches),
                "diffs": len(req.confirmed_diffs),
            }
        }
    except Exception as e:
        logger.error(f"OTA confirm error: {e}")
        raise HTTPException(status_code=500, detail=str(e))