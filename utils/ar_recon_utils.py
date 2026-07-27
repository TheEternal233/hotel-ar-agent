from datetime import datetime
import os

import openpyxl
from openpyxl.styles import Font
from copy import copy
from enums.common_enum import HEADER_FILL, HEADER_FONT, THIN_BORDER, RED_FILL, GREEN_FILL, YELLOW_FILL
from tools.ar_recon import OUT_DIR, _norm_amount
from tools.doc_parser import OTA_CHANNEL_MAPPINGS


def _unique_sheet_name(wb, name):
    """生成不重复的工作表名称。"""
    if name not in wb.sheetnames:
        return name
    i = 1
    while True:
        new_name = f"{name}_{i}"
        if new_name not in wb.sheetnames:
            return new_name
        i += 1


def _copy_sheet_to_wb(src_ws, dst_wb, title=None):

    if title is None:
        title = src_ws.title
    title = _unique_sheet_name(dst_wb, title)
    dst_ws = dst_wb.create_sheet(title=title)

    # 合并单元格
    for merged_range in src_ws.merged_cells.ranges:
        dst_ws.merge_cells(str(merged_range))

    # 列宽
    for col, dim in src_ws.column_dimensions.items():
        dst_ws.column_dimensions[col].width = dim.width

    # 行高
    for row, dim in src_ws.row_dimensions.items():
        dst_ws.row_dimensions[row].height = dim.height

    # 冻结窗格
    if src_ws.freeze_panes:
        dst_ws.freeze_panes = src_ws.freeze_panes

    # 单元格内容、公式与样式
    for row in src_ws.iter_rows():
        for cell in row:
            new_cell = dst_ws.cell(row=cell.row, column=cell.column, value=cell.value)
            if cell.has_style:
                new_cell.font = copy(cell.font)
                new_cell.border = copy(cell.border)
                new_cell.fill = copy(cell.fill)
                new_cell.number_format = copy(cell.number_format)
                new_cell.protection = copy(cell.protection)
                new_cell.alignment = copy(cell.alignment)
            if cell.hyperlink:
                new_cell.hyperlink = copy(cell.hyperlink)
            if cell.comment:
                new_cell.comment = copy(cell.comment)

    return dst_ws



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

def _match_ota_rezen_fnb(ota_records, rezen_records, channel_name):

    oci = OTA_CHANNEL_MAPPINGS.get(channel_name, {})
    price_col = oci.get("amount_col", "sell_price")

    # 统计 OTA 各金额出现次数，并收集券号
    ota_counts = {}
    ota_vouchers = {}
    ota_amount_total = 0.0
    for ota in ota_records:
        price = _norm_amount(ota.get(price_col, 0))
        if price == 0:
            continue
        ota_counts[price] = ota_counts.get(price, 0) + 1
        ota_vouchers.setdefault(price, []).append(str(ota.get("voucher_no", "") or ""))
        ota_amount_total += price

    # 统计 PMS 各金额出现次数，并收集结账单号
    pms_counts = {}
    pms_bills = {}
    pms_amount_total = 0.0
    for r in rezen_records:
        amt = _norm_amount(r.get("amount", 0))
        if amt == 0:
            continue
        pms_counts[amt] = pms_counts.get(amt, 0) + 1
        pms_bills.setdefault(amt, []).append(str(r.get("bill_no", "") or ""))
        pms_amount_total += amt

    results = []
    all_prices = set(ota_counts.keys()) | set(pms_counts.keys())
    stats = {
        "total_ota": len(ota_records),
        "total_pms": len(rezen_records),
        "match": 0,
        "diff": 0,
        "ota_only": 0,
        "pms_only": 0,
        "ota_amount_total": round(ota_amount_total, 2),
        "pms_amount_total": round(pms_amount_total, 2),
    }

    for price in sorted(all_prices):
        ota_cnt = ota_counts.get(price, 0)
        pms_cnt = pms_counts.get(price, 0)
        diff_cnt = ota_cnt - pms_cnt

        ota_amt_total = round(price * ota_cnt, 2)
        pms_amt_total = round(price * pms_cnt, 2)
        diff_amt = round(ota_amt_total - pms_amt_total, 2)

        if ota_cnt == pms_cnt and ota_cnt > 0:
            status = "match"
            stats["match"] += 1
        elif ota_cnt > 0 and pms_cnt == 0:
            status = "ota_only"
            stats["ota_only"] += 1
        elif pms_cnt > 0 and ota_cnt == 0:
            status = "pms_only"
            stats["pms_only"] += 1
        else:
            status = "diff"
            stats["diff"] += 1

        results.append({
            "status": status,
            "price": price,
            "ota_count": ota_cnt,
            "pms_count": pms_cnt,
            "diff_count": diff_cnt,
            "ota_amount_total": ota_amt_total,
            "pms_amount_total": pms_amt_total,
            "diff_amount": diff_amt,
            "ota_vouchers": ", ".join(v for v in ota_vouchers.get(price, []) if v),
            "pms_bills": ", ".join(b for b in pms_bills.get(price, []) if b),
        })

    return results, stats


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
