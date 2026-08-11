import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException
from starlette.responses import FileResponse

from deps import UPLOAD_DIR, OUTPUT_DIR, is_safe_path, logger
from schemas import FileDeleteRequest

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