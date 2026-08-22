import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from starlette.responses import FileResponse

from deps import UPLOAD_DIR, OUTPUT_DIR, is_safe_path, logger
from schemas import FileDeleteRequest
from tools.doc_parser import get_info, detect_ota_channel, validate

router = APIRouter(prefix="/api", tags=["files"])

@router.get("/files")
async def list_files(dir_type: str, sub_path: str = ""):
    if dir_type == "uploads":
        base_dir = UPLOAD_DIR
    elif dir_type == "output":
        base_dir = OUTPUT_DIR
    else:
        raise HTTPException(status_code=400, detail="dir_type必须是uploads或output")

    target_dir = base_dir / sub_path if sub_path else base_dir
    if not target_dir.exists():
        return {"ok": True, "files": [], "current_path": sub_path}

    if not is_safe_path(target_dir.resolve(), base_dir):
        raise HTTPException(status_code=403, detail="路径越界")

    items = []
    for f in sorted(target_dir.iterdir(), key=lambda x: (not x.is_dir(), x.stat().st_mtime), reverse=False):
        stat = f.stat()
        item = {
            "name": f.name,
            "path": str(f),
            "is_dir": f.is_dir(),
            "mtime": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        }
        if f.is_dir():
            item["open_url"] = f"/api/files?dir_type={dir_type}&sub_path={sub_path + '/' + f.name if sub_path else f.name}"
        else:
            item["size"] = stat.st_size
            item["download_url"] = f"/api/download?path={str(f)}"
        items.append(item)

    return {"ok": True, "files": items, "current_path": sub_path}

@router.post("/files/delete")
async def delete_file(req: FileDeleteRequest):
    try:
        fp = Path(req.path).resolve()
        if not (is_safe_path(fp, UPLOAD_DIR) or is_safe_path(fp, OUTPUT_DIR)):
            raise HTTPException(status_code=403, detail="只能删除uploads或output目录下的文件")
        if not fp.exists():
            raise HTTPException(status_code=404, detail="文件或文件夹不存在")

        if fp.is_dir():
            shutil.rmtree(fp)
        else:
            fp.unlink()

        return {"ok": True, "message": f"已删除: {fp.name}"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete file error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/files/cleanup")
async def cleanup_directory(req: dict):
    dir_type = req.get("dir_type", "")
    sub_path = req.get("sub_path", "")
    if dir_type == "uploads":
        base_dir = UPLOAD_DIR
    elif dir_type == "output":
        base_dir = OUTPUT_DIR
    else:
        raise HTTPException(status_code=400, detail="dir_type必须是uploads或output")

    target_dir = base_dir / sub_path if sub_path else base_dir
    if not is_safe_path(target_dir.resolve(), base_dir):
        raise HTTPException(status_code=403, detail="路径越界")

    deleted = 0
    for f in target_dir.iterdir():
        try:
            if f.is_dir():
                shutil.rmtree(f)
            else:
                f.unlink()
            deleted += 1
        except OSError:
            pass

    return {"ok": True, "message": f"已清理{deleted}个文件或文件夹"}

@router.get("/download")
async def download_file(path: str):
    fp = Path(path).resolve()
    if not (is_safe_path(fp, UPLOAD_DIR) or is_safe_path(fp, OUTPUT_DIR)):
        raise HTTPException(status_code=403, detail="...")
    if not fp.exists():
        raise HTTPException(status_code=404, detail="...")
    return FileResponse(path=fp, filename=fp.name, media_type="application/octet-stream")

# ========== 上传并自动检测文件格式 ==========
@router.post("/files/validate")
async def validate_uploaded_file(file: UploadFile = File(...)):
    """
    上传文件并自动检测类型、校验格式。
    自动识别: 绿云PMS / OTA渠道(携程/美团/飞猪/抖音/向蜜鸟) / 应收 / 信用卡 / 携程结算单
    返回: {ok, filename, path, size, valid, file_kind, preview, error}
    """
    # 1. 保存到 uploads
    UPLOAD_DIR.mkdir(exist_ok=True)
    file_path = (UPLOAD_DIR / file.filename).resolve()
    if not is_safe_path(file_path, UPLOAD_DIR):
        raise HTTPException(status_code=400, detail="非法文件名")

    content = await file.read()
    with open(file_path, "wb") as f:
        f.write(content)

    result = {
        "ok": True,
        "filename": file.filename,
        "path": str(file_path),
        "size": file_path.stat().st_size,
        "valid": False,
        "file_kind": None,
        "preview": None,
        "error": None,
    }

    # 2. 扩展名校验
    ext = file_path.suffix.lower()
    if ext not in (".xlsx", ".xls"):
        result["error"] = f"格式错误：仅支持 .xlsx / .xls，实际为 {ext}"
        return result

    # 3. 自动检测文件类型并校验
    try:
        info = get_info(str(file_path))
        headers = info.get("headers", [])
        headers_str = " ".join(str(h) for h in headers if h)
        result["preview"] = {
            "sheet": info.get("sheet"),
            "cols": info.get("cols"),
            "rows": info.get("rows"),
            "headers": headers[:20],
        }

        # 先尝试识别 OTA 渠道（包含 PMS 绿云）
        detected = detect_ota_channel(str(file_path))

        if detected == "rezen":
            result["file_kind"] = "绿云 PMS"
            result["valid"] = True
            return result

        if detected and detected in (
            "携程客房", "携程餐饮", "美团客房", "美团餐饮",
            "飞猪", "抖音", "向蜜鸟"
        ):
            result["file_kind"] = detected
            result["valid"] = True
            return result

        # 尝试识别其他类型
        # 应收台账特征
        aging_markers = ["客户", "customer", "到期", "due", "应收金额", "账龄"]
        aging_score = sum(1 for m in aging_markers if m in headers_str)
        if aging_score >= 2:
            ok, msg = validate(str(file_path), ["客户", "金额"])
            if ok:
                result["file_kind"] = "应收台账"
                result["valid"] = True
            else:
                result["error"] = f"疑似应收台账但缺少必要列: {msg}"
            return result

        # 信用卡/银行对账单特征
        card_markers = ["交易日期", "交易金额", "卡号", "日期", "金额", "card", "date"]
        card_score = sum(1 for m in card_markers if m in headers_str)
        if card_score >= 2:
            ok, msg = validate(str(file_path), ["日期", "金额"])
            if ok:
                result["file_kind"] = "信用卡/银行对账单"
                result["valid"] = True
            else:
                result["error"] = f"疑似对账单但缺少必要列: {msg}"
            return result

        # 携程结算单特征
        ctrip_markers = ["订单号", "间夜", "房费", "佣金", "结算"]
        ctrip_score = sum(1 for m in ctrip_markers if m in headers_str)
        if ctrip_score >= 2:
            ok, msg = validate(str(file_path), ["订单号"])
            if ok:
                result["file_kind"] = "携程结算单"
                result["valid"] = True
            else:
                result["error"] = f"疑似携程结算单但缺少必要列: {msg}"
            return result

        # 通用 PMS 兜底
        pms_markers = ["账单号", "类型", "日期", "房号", "金额"]
        pms_score = sum(1 for m in pms_markers if m in headers_str)
        if pms_score >= 2:
            ok, msg = validate(str(file_path), ["账单号", "类型"])
            if ok:
                result["file_kind"] = "PMS 报表"
                result["valid"] = True
            else:
                result["error"] = f"疑似PMS报表但缺少必要列: {msg}"
            return result

        # 无法识别
        result["error"] = "无法识别文件类型，请确保表头包含：账单号(PMS)、订单号(OTA/携程)、客户(应收)、日期+金额(对账) 等关键字"

    except Exception as e:
        logger.error(f"Validate error: {e}")
        result["error"] = f"文件解析失败: {str(e)}"

    return result