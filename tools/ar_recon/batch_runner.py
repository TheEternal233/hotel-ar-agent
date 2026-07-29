import os
from datetime import datetime

import openpyxl

from tools.ar_recon import _match_ota_rezen_fnb, _match_ota_rezen, FNB_CHANNELS, match_xiangminiao
from enums.common_enum import YELLOW_FILL, THIN_BORDER, HEADER_FILL, BASE_DIR,  OUT_DIR, HEADER_FONT
from tools.ar_recon.report_generator import _generate_report, _generate_ar_report_fnb, _generate_ar_report
from tools.doc_parser import detect_ota_channel, read_ota_channel, read_rezen
from utils.ar_recon_utils import read_xiangminiao

SUPPORTED_EXTS = (".xlsx", ".xls")
PMS_MARKER = "rezen"
DEFAULT_DATA_SUBDIR = ("data", "清远", "OTA对账")
SUMMARY_FILENAME_FMT = "OTA对账_全部汇总_{}.xlsx"
SUMMARY_SHEET_NAME = "渠道汇总"
SUMMARY_HEADERS = ["渠道", "OTA文件", "OTA记录", "PMS记录", "匹配", "差异", "仅OTA", "仅PMS", "报告文件"]
HIGHLIGHT_COLS = {5, 6, 7, 8}
PREFIX_MATCH_LEN = 2

def batch_ota_recon(data_dir=None):
    if data_dir is None:
        data_dir = os.path.join(BASE_DIR, *DEFAULT_DATA_SUBDIR)
    if not os.path.exists(data_dir):
        return f"错误：数据目录不存在: {data_dir}"

    files = [f for f in os.listdir(data_dir) if f.endswith(SUPPORTED_EXTS)]
    rezen_files = [f for f in files if PMS_MARKER in f.lower()]
    ota_files = [f for f in files if PMS_MARKER not in f.lower()]

    all_stats = []
    all_reports = []

    # Build rezen lookup by channel name
    # 将PMS文件名写成渠道名，方便配对
    rezen_lookup = {}
    for rf in rezen_files:
        rf_base = os.path.splitext(rf)[0]   #去掉.xlsx
        rf_clean = rf_base.replace(PMS_MARKER, "").replace("·", "").rstrip("0123456789")
        rezen_lookup[rf_clean] = rf

    for ota_file in ota_files:
        ota_path = os.path.join(data_dir, ota_file)
        ota_base = os.path.splitext(ota_file)[0]
        # Strip trailing digits for files like 飞猪1, 飞猪2
        channel = detect_ota_channel(ota_path)
        if channel is None or channel == "rezen":
            continue

        if channel == "向蜜鸟":
            try:
                ota_records, card_records, rezen_records = read_xiangminiao(ota_path)
            except Exception as e:
                all_stats.append(f"向蜜鸟({ota_file}): 读取失败 - {e}")
                continue
            results, stats = match_xiangminiao(ota_records, rezen_records, card_records)
            report_path = _generate_ar_report(results, stats, channel, ota_path, ota_path)
            all_stats.append({
                "channel": channel,
                "file": ota_file,
                "stats": stats,
                "report": report_path,
            })
            all_reports.append(report_path)
            continue    #跳过后续文件配对逻辑，因为向蜜鸟单个文件，不需要找rezen配对文件
        import re
        ota_clean = re.sub(r'[0-9]+$', '', ota_base).strip()
        matched_rezen = None
        for rf_clean, rf in rezen_lookup.items():
            if ota_clean in rf_clean or rf_clean in ota_clean or ota_clean[:2] in rf_clean:
                matched_rezen = rf
                break
        if matched_rezen is None:
            # Try exact prefix match
            for rf in rezen_files:
                rf_base = os.path.splitext(rf)[0]
                if ota_base[:PREFIX_MATCH_LEN] in rf_base and PMS_MARKER in rf_base.lower():
                    matched_rezen = rf
                    break
        if matched_rezen is None:
            continue
        rezen_path = os.path.join(data_dir, matched_rezen)



        try:
            ota_records = read_ota_channel(ota_path, channel)
            rezen_records = read_rezen(rezen_path)
        except Exception as e:
            all_stats.append(f"{channel}({ota_file}): 读取失败 - {e}")
            continue

        # 餐饮渠道走数量统计匹配，其他渠道走订单号匹配
        if channel in FNB_CHANNELS:
            results, stats = _match_ota_rezen_fnb(ota_records, rezen_records, channel)
            report_path = _generate_ar_report_fnb(results, stats, channel, ota_path, rezen_path)
        else:
            results, stats = _match_ota_rezen(ota_records, rezen_records, channel)
            report_path = _generate_ar_report(results, stats, channel, ota_path, rezen_path)
        all_stats.append({
            "channel": channel,
            "file": ota_file,
            "stats": stats,
            "report": report_path,
        })
        all_reports.append(report_path)

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = os.path.join(OUT_DIR, SUMMARY_FILENAME_FMT.format(now))
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SUMMARY_SHEET_NAME
    hdrs = SUMMARY_HEADERS
    for j, h in enumerate(hdrs, 1):
        c = ws.cell(row=1, column=j, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.border = THIN_BORDER

    for i, s in enumerate(all_stats, 2):
        if isinstance(s, str):
            ws.cell(row=i, column=1, value=s)
            continue
        st = s["stats"]
        vals = [s["channel"], s["file"], st["total_ota"], st["total_pms"],
                st["match"], st["diff"], st["ota_only"], st["pms_only"],
                os.path.basename(s["report"])]
        for j, v in enumerate(vals, 1):
            c = ws.cell(row=i, column=j, value=v)
            c.border = THIN_BORDER
            if j in HIGHLIGHT_COLS and isinstance(v, (int, float)) and v > 0:
                c.fill = YELLOW_FILL
    wb.save(summary_path)
    wb.close()

    total_match = sum(s["stats"]["match"] for s in all_stats if isinstance(s, dict))
    total_diff = sum(s["stats"]["diff"] for s in all_stats if isinstance(s, dict))
    total_ota_only = sum(s["stats"]["ota_only"] for s in all_stats if isinstance(s, dict))
    total_pms_only = sum(s["stats"]["pms_only"] for s in all_stats if isinstance(s, dict))

    channel_lines = []
    for s in all_stats:
        if isinstance(s, str):
            channel_lines.append(f"  {s}")
            continue
        st = s["stats"]
        channel_lines.append(
            f"  {s['channel']}: 匹配{st['match']} 差异{st['diff']} 仅OTA{st['ota_only']} 仅PMS{st['pms_only']}"
        )

    return (
        f"OTA批量对账完成\n"
        f"渠道数: {len([s for s in all_stats if isinstance(s, dict)])}\n"
        f"匹配: {total_match}  差异: {total_diff}  仅OTA: {total_ota_only}  仅PMS: {total_pms_only}\n"
        f"汇总报告: {summary_path}\n\n"
        f"各渠道明细:\n" + "\n".join(channel_lines)
    )