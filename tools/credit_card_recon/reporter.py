"""信用卡对账：差异报告生成"""

import os
from datetime import datetime

from openpyxl import Workbook
from tools import BASE_DIR
from tools.credit_card_recon.constants import (
    HEADER_FILL, HEADER_FONT, THIN_BORDER,
    RED_FILL, YELLOW_FILL, GREEN_FILL,
)


def _generate_recon_report(recon_results):
    """生成对账差异报告 Excel"""
    out_dir = os.path.join(BASE_DIR, "output")
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = os.path.join(out_dir, f"信用卡对账报告_{now}.xlsx")

    wb = Workbook()

    # Sheet 1: 对账汇总
    ws = wb.active
    ws.title = "对账汇总"
    headers = ["通道", "PMS金额", "银行金额", "差额", "手续费", "PMS条数", "银行条数", "条数平", "金额平", "状态"]
    for j, h in enumerate(headers, 1):
        c = ws.cell(row=1, column=j, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.border = THIN_BORDER

    for i, r in enumerate(recon_results, 2):
        ws.cell(row=i, column=1, value=r["channel"])
        ws.cell(row=i, column=2, value=r["pms_total"])
        ws.cell(row=i, column=3, value=r["bank_total"])
        ws.cell(row=i, column=4, value=r["diff"])
        ws.cell(row=i, column=5, value=r.get("bank_fees", 0))
        ws.cell(row=i, column=6, value=r["pms_count"])
        ws.cell(row=i, column=7, value=r["bank_count"])
        ws.cell(row=i, column=8, value="是" if r["count_match"] else "否")
        ws.cell(row=i, column=9, value="是" if abs(r["diff"]) <= 0.01 else "否")
        status = "对平" if r["balanced"] else "差异"
        c = ws.cell(row=i, column=10, value=status)
        if r["balanced"]:
            c.fill = GREEN_FILL
        else:
            c.fill = RED_FILL

    # Sheet 2: 差异明细
    ws2 = wb.create_sheet("差异明细")
    hdrs = ["通道", "类型", "金额", "来源", "原始数据"]
    for j, h in enumerate(hdrs, 1):
        c = ws2.cell(row=1, column=j, value=h)
        c.fill = HEADER_FILL
        c.font = HEADER_FONT
        c.border = THIN_BORDER

    ri = 2
    for r in recon_results:
        for um in r.get("unmatched_pms", []):
            vals = [
                r["channel"],
                "PMS短款",
                um.get("amount", 0),
                "PMS",
                str(um.get("raw", {})),
            ]
            for j, v in enumerate(vals, 1):
                c = ws2.cell(row=ri, column=j, value=v)
                c.fill = RED_FILL
                c.border = THIN_BORDER
            ri += 1
        for um in r.get("unmatched_bank", []):
            vals = [
                r["channel"],
                "银行长款",
                um.get("amount", 0),
                "BANK",
                str(um.get("raw", {})),
            ]
            for j, v in enumerate(vals, 1):
                c = ws2.cell(row=ri, column=j, value=v)
                c.fill = YELLOW_FILL
                c.border = THIN_BORDER
            ri += 1

    wb.save(out_path)
    wb.close()

    summary_lines = [
        f"通道 {r['channel']}: 差额 {r['diff']:.2f} ({'对平' if r['balanced'] else '差异'})"
        for r in recon_results
    ]
    return "对账完成\n" + "\n".join(summary_lines) + f"\n\n报告: {out_path}"
