import logging
from pathlib import Path

from graph import build_graph

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_graph = None
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
FRONTEND_DIR = BASE_DIR / "frontend"


def get_graph():
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def cleanup_uploads(file_paths: list[str]):
    for p in file_paths:
        try:
            fp = Path(p)
            if fp.exists() and UPLOAD_DIR in fp.parents:
                fp.unlink()
        except OSError:
            pass


def is_safe_path(target: Path, base: Path) -> bool:
    try:
        target.resolve().relative_to(base.resolve())
        return True
    except (OSError, ValueError):
        return False