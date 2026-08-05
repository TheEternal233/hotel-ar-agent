import os
from pathlib import Path

from openpyxl.styles import Border, Side

# 模板路径
BASE_DIR=Path(__file__).resolve().parent
NOTICE_TEMPLATE_PATH=BASE_DIR / "附件三 OTA 月度对账底稿付款通知书 模板.xlsx"
DEFAULT_OUTPUT_DIR=BASE_DIR.parent.parent / "output" / "付款通知书"

# 输出目录
_CURR_FILE = os.path.abspath(__file__)
_CURR_DIR = os.path.dirname(_CURR_FILE)
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_CURR_DIR))
DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, "output", "付款通知书")

# 模板行号
class TemplateRows:
    TO_CLIENT = 10
    DATE = 11
    SUBJECT = 14
    HEADER = 17
    OPEN_BALANCE = 18
    DETAIL_START = 19
    DETAIL_END = 33
    ADJUSTMENT = 34
    TOTAL = 36
    PAYMENT_DUE = 49

# 明细列号
class DetailCols:
    DATE = 1
    CONF_NO = 2
    GUEST_NAME = 3
    AMOUNT = 7

# 默认值
DEFAULT_ADJUSTMENT = -0.01
DEFAULT_DUE_DAYS = 30

# 样式
THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin")
)