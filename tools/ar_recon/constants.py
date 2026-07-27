import os

from openpyxl.styles import PatternFill, Font, Border
from websockets import Side

CHANNEL_NAMES = {
    "携程客房": "携程客房", "携程餐饮": "携程餐饮",
    "美团客房": "美团客房", "美团餐饮": "美团餐饮",
    "飞猪": "飞猪", "抖音": "抖音", "向蜜鸟": "向蜜鸟",
}

FNB_CHANNELS = {"美团餐饮", "携程餐饮"}
