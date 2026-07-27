
from copy import copy



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




import openpyxl

def read_xiangminiao(path):
    """向蜜鸟4-sheet单文件读取：返回 (ota_list, card_list, pms_list)"""
    wb = openpyxl.load_workbook(path, data_only=True)

    # ---------- PMS sheet ----------
    pms_list = []
    ws = wb["PMS"]
    for row in ws.iter_rows(min_row=3, values_only=True):
        if not row[0]:
            continue
        pms_list.append({
            "order": row[15] if len(row) > 15 else "",
            "ext_order": row[16] if len(row) > 16 else "",
            "amount": row[5] if len(row) > 5 else 0,
            "room": row[4] if len(row) > 4 else "",
            "remark": row[11] if len(row) > 11 else "",
            "transfer_note": row[12] if len(row) > 12 else "",
        })

    # ---------- 财务总对账 sheet（作为OTA主表）----------
    ota_list = []
    ws = wb["财务总对账"]
    for row in ws.iter_rows(min_row=3, values_only=True):
        oid = row[0]
        if not oid or str(oid) in ("订单号", "总计"):
            continue
        ota_list.append({
            "order_id": oid,
            "identify_no": row[2] if len(row) > 2 else "",
            "pay_type": row[10] if len(row) > 10 else "",
            "settle_amount": row[27] if len(row) > 27 else 0,
            "card_pay_amount": row[22] if len(row) > 22 else 0,
        })

    # ---------- 储值卡消费对账 sheet ----------
    card_list = []
    ws = wb["储值卡消费对账"]
    for row in ws.iter_rows(min_row=3, values_only=True):
        oid = row[0]
        if not oid or str(oid) in ("订单号", "总计"):
            continue
        card_list.append({
            "order_id": oid,
            "identify_no": row[2] if len(row) > 2 else "",
            "card_amount": row[11] if len(row) > 11 else 0,
        })

    wb.close()
    return ota_list, card_list, pms_list







