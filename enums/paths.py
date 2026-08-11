"""项目路径常量 —— 零依赖，所有模块均可安全导入"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
FRONTEND_DIR = BASE_DIR / "frontend"
CONFIG_DIR = BASE_DIR / "config"