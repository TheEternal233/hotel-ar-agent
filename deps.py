import logging
from pathlib import Path

from enums.paths import BASE_DIR, UPLOAD_DIR, OUTPUT_DIR, FRONTEND_DIR

from graph import build_graph

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_graph = None


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def cleanup_uploads(file_paths: list[str]):
    if not file_paths:
        return
    resolved_upload = UPLOAD_DIR.resolve()
    for p in file_paths:
        try:
            fp = Path(p).resolve()
            if fp.exists() and resolved_upload in fp.parents:
                fp.unlink()
                logger.info(f"已清理上传文件: {fp}")
        except OSError as e:
            logger.warning(f"清理文件失败: {fp} — {e}")


def is_safe_path(target: Path, base: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except (OSError, ValueError):
        return False