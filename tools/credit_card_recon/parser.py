"""信用卡对账：数据解析器

读取 PMS报表 与 POS机银行流水，按 4 种规范付款方式
（微信、支付宝、OTA卡、预付卡）分组。
挂应收、挂房账、挂团队、OC、ENT、YFD 等付款方式不统计。
"""

from tools.doc_parser import read_sheet
from tools.credit_card_recon.constants import normalize_payment


def _read_pms_report(path):
    """读取 PMS报表，按规范付款方式分组。

    - 表头在第 1 行。
    - 跳过汇总行（付款代码非纯数字的行，如「金额:/数量:」汇总行与「总计」行）。
    - 将「付款描述」映射到 4 种规范付款方式；命中排除项的不统计。

    Returns:
        dict: {规范付款方式: [{"amount", "bill_no", "raw"}, ...]}
    """
    headers, rows = read_sheet(path)
    groups = {}
    for r in rows:
        code = str(r.get("付款代码", "")).strip()
        # 跳过汇总行（付款代码不是纯数字）
        if not code.isdigit():
            continue
        desc = str(r.get("付款描述", "")).strip()
        method = normalize_payment(desc, source="pms")
        if method is None:
            continue  # 不在 4 种之内的不统计
        amt_val = r.get("金额", 0)
        try:
            amount = float(amt_val) if amt_val is not None else 0
        except (ValueError, TypeError):
            continue
        groups.setdefault(method, []).append({
            "amount": amount,
            "bill_no": str(r.get("账单号", "")),
            "raw": r,
        })
    return groups


def _read_pos_statement(path):
    """读取 POS机银行流水，按规范付款方式分组。

    - 表头在第 3 行（前两行为商户/对账单元信息）。
    - 只保留「消费」类交易，排除「押金确认」等非消费交易。
    - 将「支付类型」映射到 4 种规范付款方式；命中排除项的不统计。

    Returns:
        dict: {规范付款方式: [{"amount", "fee", "net", "tx_time", "raw"}, ...]}
    """
    headers, rows = read_sheet(path, header_row=3)
    groups = {}
    for r in rows:
        pay_type = str(r.get("支付类型", "")).strip()
        tx_type = str(r.get("交易类型", "")).strip()
        if not pay_type:
            continue
        # 只统计消费类交易，排除押金确认等
        if tx_type and tx_type not in ("消费", "sale", "charge"):
            continue
        method = normalize_payment(pay_type, source="pos")
        if method is None:
            continue  # 不在 4 种之内的不统计
        groups.setdefault(method, []).append({
            "amount": float(r.get("客户实付金额", 0) or 0),
            "fee": float(r.get("手续费金额", 0) or 0),
            "net": float(r.get("入账金额", 0) or 0),
            "tx_time": r.get("交易时间"),
            "raw": r,
        })
    return groups
