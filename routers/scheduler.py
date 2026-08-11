import os

from fastapi import APIRouter, HTTPException

from tools.protocol_settlement.aging_pms import aging_analysis
from tools.ctrip_commission_reconcile.ctrip_commission import ctrip_commission
from deps import BASE_DIR, UPLOAD_DIR, logger

router = APIRouter(prefix="/api", tags=["scheduler"])


@router.post("/scheduler/{mode}")
async def scheduler_run(mode: str):
    results = []
    try:
        if mode == "daily":
            from tools.credit_card_recon import batch_card_recon
            r = batch_card_recon(os.path.join(BASE_DIR, "data", "清远", "信用卡对账"))
            results.append(f"[信用卡对账] {r}")
            if not results:
                results.append("未找到数据文件")

        elif mode == "monthly":
            uploads = list(UPLOAD_DIR.glob("*.xlsx")) if UPLOAD_DIR.exists() else []
            upload_map = {f.name: str(f) for f in uploads}

            ota_file = upload_map.get("AR审核_OTA.xlsx", "")
            pms_file = upload_map.get("AR审核_PMS.xlsx", "")
            aging_file = upload_map.get("应收账龄分析表.xlsx", "")

            from tools.ar_recon import batch_ota_recon
            r = batch_ota_recon(os.path.join(BASE_DIR, "data", "清远", "OTA对账"))
            results.append(f"[OTA对账] {r}")
            if aging_file:
                r = aging_analysis.invoke({"receivable_path": aging_file, "as_of_date": ""})
                results.append(f"[账龄分析] {r}")
            ctrip_files = [f for f in upload_map if "携程" in f or "ctrip" in f.lower()]
            if ctrip_files:
                pms_files = [f for f in upload_map if "pms" in f.lower()]
                r = ctrip_commission.invoke({
                    "ctrip_filename": upload_map[ctrip_files[0]],
                    "pms_filename": upload_map[pms_files[0]] if pms_files else "",
                })
                results.append(f"[携程佣金] {r}")
            if not results:
                results.append("uploads目录下未找到匹配文件，请先上传数据文件")

        else:
            raise HTTPException(status_code=400, detail=f"Unknown mode: {mode}")

        return {"ok": True, "results": results}
    except Exception as e:
        logger.error(f"Scheduler {mode} error: {e}")
        raise HTTPException(status_code=500, detail=str(e))