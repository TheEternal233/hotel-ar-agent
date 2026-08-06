# -*- coding: utf-8 -*-
"""M04: 携程佣金核对工具（整合 Parser + Reconciler）"""
import os
from datetime import datetime


import pandas as pd
from langchain_core.tools import tool
from openpyxl.styles import PatternFill, Font, Border, Side

from tools.ctrip_commission_reconcile.CommissionReconciler import CommissionReconciler
from tools.ctrip_commission_reconcile.CtripCommissionParser import CtripCommissionParser
from tools.ctrip_commission_reconcile.PmsParser import PmsParser
from openpyxl.styles import PatternFill, Font, Border, Side, Alignment

_HEADER_FILL = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_THIN_BORDER = Border(
    left=Side(style="thin"), right=Side(style="thin"),
    top=Side(style="thin"), bottom=Side(style="thin")
)

# 状态颜色映射
_STATUS_FILL = {
    "OK":           PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid"),  # 淡绿
    "DIFF":         PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid"),  # 淡红
    "UNMATCHED":    PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),  # 淡黄
    "NO_PMS_PRICE": PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid"),  # 淡黄
}
# 项目根目录（tools/ 的上一级）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_DIR = os.path.join(_BASE_DIR, "uploads")
OUTPUT_DIR = os.path.join(_BASE_DIR, "output")

_RED_FILL = PatternFill(start_color="FFCCCC", end_color="FFCCCC", fill_type="solid")



@tool
def ctrip_commission(ctrip_filename:str,pms_filename:str)->str:
    """
    携程佣金核对：读取 uploads 下的携程结算单，可选加载 PMS，自动匹配验算后输出差异表到 output。

    Args:
        ctrip_filename: uploads 目录下的携程文件名，如 "携程佣金.xls"
        pms_filename: uploads 目录下的 PMS 文件名（可选），如 "pms.xlsx"
    """
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 读取携程
    ctrip_path=os.path.join(UPLOAD_DIR,ctrip_filename)
    if not os.path.exists(ctrip_path):
        return f"error: file not found: {ctrip_path}"

    ctrip_parser = CtripCommissionParser()
    ctrip_records = ctrip_parser.parse(ctrip_path)
    if not ctrip_records:
        return f"error: 携程账单解析为空，请检查文件内容"

    total_orders=len(ctrip_records)
    total_nights=sum(r["nights"] for r in ctrip_records)
    total_comm=sum(r["commission"] for r in ctrip_records)

    #读取PMS
    has_pms=bool(pms_filename and pms_filename.strip())
    pms_records=[]

    if has_pms:
        pms_path=os.path.join(UPLOAD_DIR,pms_filename)
        if not os.path.exists(pms_path):
            return f"error: PMS file not found: {pms_path}"
        pms_parser = PmsParser()
        pms_records = pms_parser.parse(pms_path)

    # 核对
    recon=CommissionReconciler(commission_rate=0.15,tolerance=0.05)
    recon.load_ctrip(ctrip_records)

    if pms_records:
        recon.load_pms(pms_records)
    result=recon.run()

    ok_count=sum(1 for r in result if r["status"]=="OK")
    diff_count=sum(1 for r in result if r["status"]=="DIFF")
    unmatched_count=sum(1 for r in result if r["status"] in ("UNMATCHED","NO_PMS_PRICE"))

    # 输出Excel
    timetamp=datetime.now().strftime("%Y%m%d_%H%M%S")
    out_name=f"ctrip_recon_{timetamp}.xlsx"
    out_path=os.path.join(OUTPUT_DIR,out_name)

    df=pd.DataFrame(result)

    with pd.ExcelWriter(out_path,engine="openpyxl") as writer:
        #sheet1 全部结果
        df.to_excel(writer,sheet_name="核对结果",index=False)
        ws=writer.sheets["核对结果"]

        # 1.表头样式
        for cell in ws[1]:
            cell.fill=_HEADER_FILL
            cell.font=_HEADER_FONT
            cell.border=_THIN_BORDER
            cell.alignment=Alignment(horizontal="center", vertical="center")

        # 2.找到status列的索引
        status_col_idx=None
        for idx,col_name in enumerate(df.columns,start=1):
            if col_name == "status":
                status_col_idx=idx
                break
        # 按行染色加边框
        for row in ws.iter_rows(min_row=2,max_row=ws.max_row):
            status_val=row[status_col_idx-1].value if status_col_idx else None
            fill=_STATUS_FILL.get(status_val)

            for cell in row:
                cell.border=_THIN_BORDER
                cell.alignment=Alignment(vertical="center")
                if fill:
                    cell.fill=fill

        #sheet2需关注
        attention=df[df["status"].isin(["DIFF","UNMATCHED","NO_PMS_PRICE"])]
        if not attention.empty:
            attention.to_excel(writer,sheet_name="需关注",index=False)
            ws2=writer.sheets["需关注"]

            #表头
            for cell in ws2[1]:
                cell.fill=_HEADER_FILL
                cell.font=_HEADER_FONT
                cell.border=_THIN_BORDER

            #全部染成对应颜色
            for row in ws2.iter_rows(min_row=2,max_row=ws2.max_row):
                status_val=row[status_col_idx-1].value if status_col_idx else None
                fill=_STATUS_FILL.get(status_val)
                for cell in row:
                    cell.border=_THIN_BORDER
                    if fill:
                        cell.fill=fill

        #sheet3 摘要
        summary_rows=[
            ("总记录", len(df)),
            ("携程原始条数", total_orders),
            ("PMS原始条数", len(pms_records) if has_pms else 0),
            ("正常", ok_count),
            ("佣金差异", diff_count),
            ("未匹配/无房价", unmatched_count),
            ("佣金率", 0.15),
            ("容差(元)", 0.05),
        ]

        pd.DataFrame(summary_rows,columns=["指标","数值"]).to_excel(writer,sheet_name="摘要",index=False)

        ws3=writer.sheets["摘要"]
        for cell in ws3[1]:
            cell.fill=_HEADER_FILL
            cell.font=_HEADER_FONT
            cell.border=_THIN_BORDER

        # 返回
        base_msg=(
            f"done: {out_path} "
            f"orders={total_orders} nights={int(total_nights)} comm={total_comm:,.2f}"
        )
        if has_pms:
            return f"{base_msg} ok={ok_count} diffs={diff_count} unmatched={unmatched_count}"
        else:
            return f"{base_msg} pms=skipped (parsed only)"



