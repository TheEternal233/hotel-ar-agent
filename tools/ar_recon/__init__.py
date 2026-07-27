import os
from langchain.tools import tool
from tools.ar_recon.constants import FNB_CHANNELS
from enums.common_enum import OUT_DIR
from tools.ar_recon.matcher import _match_ota_rezen, _match_ota_rezen_fnb, match_xiangminiao
from tools.ar_recon.batch_runner import batch_ota_recon
from tools.ar_recon.report_generator import _generate_ar_report_fnb, _generate_report, _generate_ar_report
from tools.doc_parser import read_ota_channel, read_rezen, detect_ota_channel
from utils.ar_recon_utils import read_xiangminiao

os.makedirs(OUT_DIR, exist_ok=True)

@tool
def ar_recon(ota_path: str = "", pms_path: str = "", channel: str = "") -> str:
    """OTA对账：输入OTA导出和PMS(rezen)两个xlsx路径及渠道名，自动匹配并输出差额报告。

    渠道可选: 携程客房, 携程餐饮, 美团客房, 美团餐饮, 飞猪, 抖音, 向蜜鸟
    留空则自动检测渠道。
    不传参数时自动执行 data/清远/OTA对账 目录下的批量对账。
    """
    if not ota_path and not pms_path:
        return batch_ota_recon()

    if not ota_path or not pms_path:
        return "错误：请同时提供 ota_path 和 pms_path，或都不提供进行批量对账"

    if not os.path.exists(ota_path):
        return f"错误：OTA文件不存在: {ota_path}"
    if not os.path.exists(pms_path):
        return f"错误：PMS文件不存在: {pms_path}"

    if not channel:
        channel = detect_ota_channel(ota_path)
        if channel is None or channel == "rezen":
            return f"无法自动检测渠道，请手动指定 channel 参数。"

    try:
        if channel == "向蜜鸟":
            # 两张路径指向同一个4-sheet文件
            target = ota_path if os.path.exists(ota_path) else pms_path
            ota_records, card_records, rezen_records = read_xiangminiao(target)
            results, stats = match_xiangminiao(ota_records, rezen_records, card_records)
            report_path = _generate_report(results, stats, channel, ota_path, pms_path)
        elif channel in FNB_CHANNELS:
            ota_records = read_ota_channel(ota_path, channel)
            rezen_records = read_rezen(pms_path)
            results, stats = _match_ota_rezen_fnb(ota_records, rezen_records, channel)
            report_path = _generate_ar_report_fnb(results, stats, channel, ota_path, pms_path)
        else:
            ota_records = read_ota_channel(ota_path, channel)
            rezen_records = read_rezen(pms_path)
            results, stats = _match_ota_rezen(ota_records, rezen_records, channel)
            report_path = _generate_ar_report(results, stats, channel, ota_path, pms_path)
    except Exception as e:
        return f"读取文件失败: {e}"



    return (
        f"OTA对账完成 [{channel}]\n"
        f"报告: {report_path}\n"
        f"OTA记录: {stats['total_ota']}  PMS记录: {stats['total_pms']}\n"
        f"匹配: {stats['match']}  差异: {stats['diff']}  仅OTA: {stats['ota_only']}  仅PMS: {stats['pms_only']}"
    )

__all__ = ["ar_recon"]