CHANNEL_NAMES = {
    "携程客房": "携程客房", "携程餐饮": "携程餐饮",
    "美团客房": "美团客房", "美团餐饮": "美团餐饮",
    "飞猪": "飞猪", "抖音": "抖音", "向蜜鸟": "向蜜鸟",
}

FNB_CHANNELS = {"美团餐饮", "携程餐饮"}

AMOUNT_TOLERANCE = 0.02      # 金额匹配容差（订单号/识别号精确匹配）
DIFF_TOLERANCE = 0.02        # 差额判定容差
MAX_AMOUNT_DIFF = 5.0        # 无单号时金额兜底最大差异

PMS_MARKER = "rezen"
SUPPORTED_EXTS = (".xlsx", ".xls")
DEFAULT_DATA_SUBDIR = ("data", "清远", "OTA对账")
PREFIX_MATCH_LEN = 2

REPORT_FILENAME_FMT = "OTA对账_{}_{}.xlsx"
SUMMARY_FILENAME_FMT = "OTA对账_全部汇总_{}.xlsx"
XIANGMINIAO_OTA_SHEET = "财务总对账"
SHEET_SUMMARY = "对账汇总"
SHEET_DIFF = "差额明细"
SHEET_FULL = "全额对比"
SUMMARY_SHEET_NAME = "渠道汇总"

STATUS_MATCH = "match"
STATUS_DIFF = "diff"
STATUS_OTA_ONLY = "ota_only"
STATUS_PMS_ONLY = "pms_only"

SUMMARY_HEADERS = ["渠道", "OTA文件", "OTA记录", "PMS记录", "匹配", "差异", "仅OTA", "仅PMS", "报告文件"]
HIGHLIGHT_COLS = {5, 6, 7, 8}

STD_DIFF_HDRS = ["OTA订单号", "PMS外部订单号", "OTA金额", "PMS金额", "差额", "状态", "房号", "PMS备注"]
STD_FULL_HDRS = ["状态", "OTA订单号", "PMS外部订单号", "OTA金额", "PMS金额", "差额", "房号"]
FNB_DIFF_HDRS = ["金额", "OTA数量", "PMS数量", "数量差异", "OTA金额", "PMS金额", "金额差异", "状态", "OTA券号", "PMS结账单号"]
FNB_FULL_HDRS = ["状态", "金额", "OTA数量", "PMS数量", "数量差异", "OTA金额", "PMS金额", "金额差异", "OTA券号", "PMS结账单号"]
AR_DIFF_HDRS = ["状态", "OTA单号", "OTA金额", "差额", "备注"]

STATUS_ORDER = {STATUS_MATCH: 0, STATUS_DIFF: 1, STATUS_PMS_ONLY: 2, STATUS_OTA_ONLY: 3}

OTA_RECON_DIR = "OTA对账"
OTA_PREFIX = "OTA"
PMS_PREFIX = "PMS"