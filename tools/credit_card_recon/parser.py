"""信用卡对账：数据解析器集合

包含 PMS报表、POS银行流水、PMS应收后台、YFD银行流水 的专用解析器。
"""

from tools.doc_parser import read_sheet, read_rezen
from tools.credit_card_recon.matcher import classify_channel, split_debit_credit


def read_yfd_bank(path, sheet_name=None):
    """读取YFD银行流水 — 表头在第5行，过滤RD数据行和RT汇总行"""
    from tools.doc_parser import _open, _get_headers

    wb, ws = _open(path, sheet_name)
    headers = _get_headers(ws, header_row=5)

    records = []
    for row in ws.iter_rows(min_row=6, values_only=True):
        if all(v is None for v in row):
            continue
        # 第一列 'RD' = 数据行, 'RT' = 汇总行
        file_info = str(row[0] or "").strip()
        if file_info != "RD":
            continue

        rec = dict(zip(headers, row))
        records.append({
            "amount": float(rec.get("金额", 0) or 0),
            "fee": float(rec.get("服务佣金", 0) or 0),
            "net": float(rec.get("结算金额", 0) or 0),
            "terminal": str(rec.get("终端号", "")),
            "tx_type": str(rec.get("交易类型", "")),
            "tx_time": str(rec.get("交易时间", "")),
            "store": str(rec.get("店铺名称", "")),
            "raw": rec,
        })
    wb.close()
    return records


def _read_pms_report(path):
    """读取 PMS报表，按付款描述分组

    过滤掉汇总行（付款代码非数字的行），按 desc 列分组。
    """
    headers, rows = read_sheet(path)
    payment_groups = {}
    for r in rows:
        code = str(r.get("付款代码", "")).strip()
        # 跳过汇总行
        if not code.isdigit():
            continue
        desc = str(r.get("付款描述", "")).strip()
        amt_val = r.get("金额", 0)
        try:
            amount = float(amt_val) if amt_val is not None else 0
        except (ValueError, TypeError):
            continue
        pay_type = desc if desc else None
        if pay_type not in payment_groups:
            payment_groups[pay_type] = []
        payment_groups[pay_type].append({
            "amount": amount,
            "bill_no": str(r.get("账单号", "")),
            "raw": r,
        })
    return payment_groups


def _read_pos_statement(path):
    """读取 POS机银行流水，过滤非消费类交易

    表头在第3行，只保留"消费"类交易（排除押金确认等）。
    """
    headers, rows = read_sheet(path, header_row=3)
    records = []
    for r in rows:
        pay_type = str(r.get("支付类型", "")).strip()
        tx_type = str(r.get("交易类型", "")).strip()
        if not pay_type:
            continue
        # 只统计消费类交易，排除押金确认等
        if tx_type and tx_type not in ("消费", "sale", "charge"):
            continue
        records.append({
            "amount": float(r.get("客户实付金额", 0) or 0),
            "fee": float(r.get("手续费金额", 0) or 0),
            "net": float(r.get("入账金额", 0) or 0),
            "pay_type": pay_type,
            "tx_type": tx_type,
            "tx_time": r.get("交易时间"),
            "raw": r,
        })
    return records


def _read_pms_ar_backend(path):
    """读取 PMS应收后台，分离借方/贷方，只保留收款"""
    records = read_rezen(path)
    charges, refunds = split_debit_credit(records)

    result = []
    for r in charges:
        result.append({
            "amount": float(r.get("amount", 0)),
            "bill_no": str(r.get("bill_id", "")),
            "channel": classify_channel(r.get("name", "")),
            "name": r.get("name", ""),
            "raw": r,
        })
    return result
