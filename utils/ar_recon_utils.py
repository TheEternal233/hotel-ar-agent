
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








