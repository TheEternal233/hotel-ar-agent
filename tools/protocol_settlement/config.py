import os
from pathlib import Path

from enums.common_enum import THIN_BORDER

BASE_DIR=Path(__file__).resolve().parent
# 模板路径

NOTICE_TEMPLATE_PATH=BASE_DIR / "附件三 OTA 月度对账底稿付款通知书 模板.xlsx"


# 输出目录
DEFAULT_OUTPUT_DIR=BASE_DIR.parent.parent / "output" / "付款通知书"

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
DEFAULT_ADJUSTMENT = 0.0
DEFAULT_DUE_DAYS = 30