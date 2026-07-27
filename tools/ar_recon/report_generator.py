import os
from datetime import datetime

import openpyxl
from openpyxl.styles import Font

from enums.common_enum import  OUT_DIR, HEADER_FILL, HEADER_FONT, THIN_BORDER, RED_FILL, GREEN_FILL, YELLOW_FILL

from utils.ar_recon_utils import _copy_sheet_to_wb


def _generate_report(results, stats, channel_name, ota_path, pms_path):
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    cname = channel_name.replace("·", "_")
    out_path = os.path.join(OUT_DIR, f"OTA对账_{cname}_{now}.xlsx")

    wb = openpyxl.Workbook()

    ws1 = wb.active
    ws1.title = "对账汇总"
    info = [
        ("渠道", channel_name),
        ("OTA文件", os.path.basename(ota_path)),
        ("PMS文件", os.path.basename(pms_path)),
        ("对账时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("", ""),
        ("OTA记录数", stats["total_ota"]),
        ("PMS记录数", stats["total_pms"]),
        ("完全匹配", stats["match"]),
        ("金额差异", stats["diff"]),
        ("仅OTA存在", stats["ota_only"]),
        ("仅PMS存在", stats["pms_only"]),
        ("", ""),
        ("OTA金额合计", round(sum(r["ota_amount"] for r in results if r["status"] != "pms_only"), 2)),
        ("PMS金额合计", round(sum(r["pms_amount"] for r in results if r["status"] != "ota_only"), 2)),
        ("净差异", round(sum(r["diff"] for r in results if r["status"] == "diff"), 2)),
    ]
    for i, (k, v) in enumerate(info, 1):
        ws1.cell(row=i, column=1, value=k).font = Font(bold=True)
        c = ws1.cell(row=i, column=2, value=v)
        if "差异" in str(k) and isinstance(v, (int, float)) and v != 0:
            c.fill = RED_FILL

    ws2 = wb.create_sheet("差额明细")
    hdrs2 = ["OTA订单号", "PMS外部订单号", "OTA金额", "PMS金额", "差额", "状态", "房号", "PMS备注"]
    for j, h in enumerate(hdrs2, 1):
        c = ws2.cell(row=1, column=j, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.border = THIN_BORDER

    ri = 2
    for r in results:
        if r["status"] == "match":
            continue
        pms = r.get("pms") or {}
        vals = [
            r["ota_order"],
            r["pms_ext_order"],
            r["ota_amount"],
            r["pms_amount"],
            r["diff"],
            r["status"],
            str(pms.get("room", "")),
            str(pms.get("remark", "")),
        ]
        for j, v in enumerate(vals, 1):
            c = ws2.cell(row=ri, column=j, value=v)
            c.border = THIN_BORDER
            if r["status"] == "diff":
                c.fill = RED_FILL
            elif r["status"] in ("ota_only", "pms_only"):
                c.fill = YELLOW_FILL
        ri += 1

    ws3 = wb.create_sheet("全额对比")
    hdrs3 = ["状态", "OTA订单号", "PMS外部订单号", "OTA金额", "PMS金额", "差额", "房号"]
    for j, h in enumerate(hdrs3, 1):
        c = ws3.cell(row=1, column=j, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.border = THIN_BORDER

    ri = 2
    for r in results:
        pms = r.get("pms") or {}
        vals = [
            r["status"],
            r["ota_order"],
            r["pms_ext_order"],
            r["ota_amount"],
            r["pms_amount"],
            r["diff"],
            str(pms.get("room", "")),
        ]
        for j, v in enumerate(vals, 1):
            c = ws3.cell(row=ri, column=j, value=v)
            c.border = THIN_BORDER
            if r["status"] == "match":
                c.fill = GREEN_FILL
            elif r["status"] == "diff":
                c.fill = RED_FILL
            elif r["status"] in ("ota_only", "pms_only"):
                c.fill = YELLOW_FILL
        ri += 1

    wb.save(out_path)
    wb.close()
    return out_path


def _generate_ar_report(results, stats, channel_name, ota_path, pms_path):

    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    cname = channel_name.replace("·", "_")
    out_path = os.path.join(OUT_DIR, f"OTA对账_{cname}_{now}.xlsx")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # 删除默认 sheet

    # ---------- 复制 PMS 源文件 ----------
    pms_wb = openpyxl.load_workbook(pms_path, data_only=False)
    for idx, ws in enumerate(pms_wb.worksheets):
        _copy_sheet_to_wb(ws, wb, title="PMS" if idx==0 else None)
    pms_wb.close()

    # ---------- 复制 OTA 原文件 ----------
    ota_wb = openpyxl.load_workbook(ota_path, data_only=False)
    for idx, ws in enumerate(ota_wb.worksheets):
        _copy_sheet_to_wb(ws, wb, title="OTA" if idx==0 else None)
    ota_wb.close()

    # ---------- 对账汇总 ----------
    ws_sum = wb.create_sheet("对账汇总")
    row = 1

    # 1) 汇总统计区
    info = [
        ("渠道", channel_name),
        ("OTA文件", os.path.basename(ota_path)),
        ("PMS文件", os.path.basename(pms_path)),
        ("对账时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("", ""),
        ("OTA记录数", stats["total_ota"]),
        ("PMS记录数", stats["total_pms"]),
        ("完全匹配", stats["match"]),
        ("金额差异", stats["diff"]),
        ("仅OTA存在", stats["ota_only"]),
        ("仅PMS存在", stats["pms_only"]),
        ("", ""),
        ("OTA金额合计", round(sum(r["ota_amount"] for r in results if r["status"] != "pms_only"), 2)),
        ("PMS金额合计", round(sum(r["pms_amount"] for r in results if r["status"] != "ota_only"), 2)),
        ("净差异", round(sum(r["diff"] for r in results if r["status"] == "diff"), 2)),
    ]
    for k, v in info:
        ws_sum.cell(row=row, column=1, value=k).font = Font(bold=True)
        c = ws_sum.cell(row=row, column=2, value=v)
        if "差异" in str(k) and isinstance(v, (int, float)) and v != 0:
            c.fill = RED_FILL
        row += 1

    row += 1  # 空行

    # 2) 差额明细区
    ws_sum.cell(row=row, column=1, value="差额明细（仅展示未匹配/有差异的记录）").font = Font(bold=True, size=12)
    row += 1
    hdrs_diff = ["OTA订单号", "PMS外部订单号", "OTA金额", "PMS金额", "差额", "状态", "房号", "PMS备注"]
    for j, h in enumerate(hdrs_diff, 1):
        c = ws_sum.cell(row=row, column=j, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.border = THIN_BORDER
    row += 1

    for r in results:
        if r["status"] == "match":
            continue
        pms = r.get("pms") or {}
        vals = [
            r["ota_order"],
            r["pms_ext_order"],
            r["ota_amount"],
            r["pms_amount"],
            r["diff"],
            r["status"],
            str(pms.get("room", "")),
            str(pms.get("remark", "")),
        ]
        for j, v in enumerate(vals, 1):
            c = ws_sum.cell(row=row, column=j, value=v)
            c.border = THIN_BORDER
            if r["status"] == "diff":
                c.fill = RED_FILL
            elif r["status"] in ("ota_only", "pms_only"):
                c.fill = YELLOW_FILL
        row += 1

    row += 1  # 空行

    # 3) 全额对比区
    ws_sum.cell(row=row, column=1, value="全额对比（含匹配记录）").font = Font(bold=True, size=12)
    row += 1
    hdrs_full = ["状态", "OTA订单号", "PMS外部订单号", "OTA金额", "PMS金额", "差额", "房号"]
    for j, h in enumerate(hdrs_full, 1):
        c = ws_sum.cell(row=row, column=j, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.border = THIN_BORDER
    row += 1

    for r in results:
        pms = r.get("pms") or {}
        vals = [
            r["status"],
            r["ota_order"],
            r["pms_ext_order"],
            r["ota_amount"],
            r["pms_amount"],
            r["diff"],
            str(pms.get("room", "")),
        ]
        for j, v in enumerate(vals, 1):
            c = ws_sum.cell(row=row, column=j, value=v)
            c.border = THIN_BORDER
            if r["status"] == "match":
                c.fill = GREEN_FILL
            elif r["status"] == "diff":
                c.fill = RED_FILL
            elif r["status"] in ("ota_only", "pms_only"):
                c.fill = YELLOW_FILL
        row += 1

    wb.save(out_path)
    wb.close()
    return out_path

def _generate_ar_report_fnb(results, stats, channel_name, ota_path, pms_path):
    """餐饮渠道专用报告：按售价/卖价金额统计数量并比对。

    输出结构仍为：PMS 源文件 + OTA 原文件 + 对账汇总。
    对账汇总中按金额分组，展示 OTA/PMS 各自的数量、金额及差异。
    """
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    cname = channel_name.replace("·", "_")
    out_path = os.path.join(OUT_DIR, f"OTA对账_{cname}_{now}.xlsx")

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # 删除默认 sheet

    # ---------- 复制 PMS 源文件 ----------
    pms_wb = openpyxl.load_workbook(pms_path, data_only=False)
    for idx, ws in enumerate(pms_wb.worksheets):
        _copy_sheet_to_wb(ws, wb, title="PMS" if idx == 0 else None)
    pms_wb.close()

    # ---------- 复制 OTA 原文件 ----------
    ota_wb = openpyxl.load_workbook(ota_path, data_only=False)
    for idx, ws in enumerate(ota_wb.worksheets):
        _copy_sheet_to_wb(ws, wb, title="OTA" if idx == 0 else None)
    ota_wb.close()

    # ---------- 对账汇总 ----------
    ws_sum = wb.create_sheet("对账汇总")
    row = 1

    # 1) 汇总统计区
    info = [
        ("渠道", channel_name),
        ("OTA文件", os.path.basename(ota_path)),
        ("PMS文件", os.path.basename(pms_path)),
        ("对账时间", datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        ("", ""),
        ("OTA记录数", stats["total_ota"]),
        ("PMS记录数", stats["total_pms"]),
        ("数量完全匹配", stats["match"]),
        ("数量差异", stats["diff"]),
        ("仅OTA存在", stats["ota_only"]),
        ("仅PMS存在", stats["pms_only"]),
        ("", ""),
        ("OTA金额合计", stats.get("ota_amount_total", 0)),
        ("PMS金额合计", stats.get("pms_amount_total", 0)),
        ("净金额差异", round(sum(r["diff_amount"] for r in results if r["status"] == "diff"), 2)),
    ]
    for k, v in info:
        ws_sum.cell(row=row, column=1, value=k).font = Font(bold=True)
        c = ws_sum.cell(row=row, column=2, value=v)
        if ("差异" in str(k) or "差额" in str(k)) and isinstance(v, (int, float)) and v != 0:
            c.fill = RED_FILL
        row += 1

    row += 1  # 空行

    # 2) 差额明细区（仅展示数量不一致或单边存在的金额）
    ws_sum.cell(row=row, column=1, value="差额明细（按金额分组，仅展示数量不一致的记录）").font = Font(bold=True, size=12)
    row += 1
    hdrs_diff = ["金额", "OTA数量", "PMS数量", "数量差异", "OTA金额", "PMS金额", "金额差异", "状态", "OTA券号", "PMS结账单号"]
    for j, h in enumerate(hdrs_diff, 1):
        c = ws_sum.cell(row=row, column=j, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.border = THIN_BORDER
    row += 1

    for r in results:
        if r["status"] == "match":
            continue
        vals = [
            r["price"],
            r["ota_count"],
            r["pms_count"],
            r["diff_count"],
            r["ota_amount_total"],
            r["pms_amount_total"],
            r["diff_amount"],
            r["status"],
            r.get("ota_vouchers", ""),
            r.get("pms_bills", ""),
        ]
        for j, v in enumerate(vals, 1):
            c = ws_sum.cell(row=row, column=j, value=v)
            c.border = THIN_BORDER
            if r["status"] == "diff":
                c.fill = RED_FILL
            elif r["status"] in ("ota_only", "pms_only"):
                c.fill = YELLOW_FILL
        row += 1

    row += 1  # 空行

    # 3) 全额对比区（含数量匹配的记录）
    ws_sum.cell(row=row, column=1, value="全额对比（含数量匹配记录）").font = Font(bold=True, size=12)
    row += 1
    hdrs_full = ["状态", "金额", "OTA数量", "PMS数量", "数量差异", "OTA金额", "PMS金额", "金额差异", "OTA券号", "PMS结账单号"]
    for j, h in enumerate(hdrs_full, 1):
        c = ws_sum.cell(row=row, column=j, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.border = THIN_BORDER
    row += 1

    for r in results:
        vals = [
            r["status"],
            r["price"],
            r["ota_count"],
            r["pms_count"],
            r["diff_count"],
            r["ota_amount_total"],
            r["pms_amount_total"],
            r["diff_amount"],
            r.get("ota_vouchers", ""),
            r.get("pms_bills", ""),
        ]
        for j, v in enumerate(vals, 1):
            c = ws_sum.cell(row=row, column=j, value=v)
            c.border = THIN_BORDER
            if r["status"] == "match":
                c.fill = GREEN_FILL
            elif r["status"] == "diff":
                c.fill = RED_FILL
            elif r["status"] in ("ota_only", "pms_only"):
                c.fill = YELLOW_FILL
        row += 1

    wb.save(out_path)
    wb.close()
    return out_path