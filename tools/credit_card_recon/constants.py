"""信用卡对账：常量和映射表"""

from openpyxl.styles import Font, PatternFill, Border, Side

# Excel 样式
HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
HEADER_FONT = Font(color="FFFFFF", bold=True)
THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin"),
)
RED_FILL = PatternFill(start_color="FFCCCC", end_color="FFCCCC", fill_type="solid")
YELLOW_FILL = PatternFill(start_color="FFFFCC", end_color="FFFFCC", fill_type="solid")
GREEN_FILL = PatternFill(start_color="CCFFCC", end_color="CCFFCC", fill_type="solid")

# 付款代码→支付方式映射（清远酒店 PMS，备用）
PAYMENT_CODE_MAP = {
    "9005": "微信",
    "9006": "支付宝",
    "9007": "挂应收",
    "9008": "挂房账",
    "9009": "挂团队",
    "9011": "OC",
    "9012": "ENT",
    "9019": "YFD微信",
}

# POS支付类型 → 对账通道
PAY_TYPE_TO_CHANNEL = {
    "微信支付": "WECHAT",
    "支付宝支付": "ALIPAY",
}

# YFD银行流水交易类型 → 对账通道
YFD_TYPE_MAP = {
    "ALIPAY": "YFD_ALIPAY",
    "TENPAY": "YFD_WECHAT",
}
