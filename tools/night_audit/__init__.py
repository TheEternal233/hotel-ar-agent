"""night_audit: 每日夜审汇总工具"""
from typing import List

from langchain_core.tools import tool

from .aggregator import aggregate_daily_check
from .api import daily_check_handler


@tool
def night_audit_tool(ota_paths:List[str],card_paths:List[str])->str:
    """
    夜审报表汇总工具。接受OTA对账结果和信用卡对账结果的Excel文件路径，汇总生成单一夜审Excel报表并返回汇总报告

    当用户要求生成夜审报表，汇总OTA和信用卡对账结果，或进行每日夜审时调用此工具

    Args:
        ota_paths: OTA对账结果Excel文件路径列表，例如 ["/uploads/ota_recon_1.xlsx"]
        card_paths: 信用卡对账结果Excel文件路径列表，例如 ["/uploads/card_recon_1.xlsx"]

    Returns:
        汇总报告文本，包含生成文件路径和统计信息
    """
    try:
        return daily_check_handler(ota_paths,card_paths)
    except Exception as e:
        return f"夜审汇总失败：{e}"



__all__ = ["aggregate_daily_check", "daily_check_handler","night_audit_tool"]