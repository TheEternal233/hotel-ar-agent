"""M07: 信用卡对账 — 按支付方式分组 + YFD预付卡独立通道

入口文件。负责文件分类、数据流编排、对账调度、报告输出。
解析/对账/报告逻辑分别下沉到 parser / matcher / reporter 模块。
"""

import os
from datetime import datetime

try:
    from langchain.tools import tool
    _HAS_LANGCHAIN = True
except ImportError:
    _HAS_LANGCHAIN = False
    def tool(fn):
        return fn

from tools import BASE_DIR
from tools.credit_card_recon.parser import (
    read_yfd_bank, _read_pms_report, _read_pos_statement, _read_pms_ar_backend,
)
from tools.credit_card_recon.matcher import _reconcile_channel
from tools.credit_card_recon.reporter import _generate_recon_report
from tools.credit_card_recon.constants import PAY_TYPE_TO_CHANNEL, YFD_TYPE_MAP
from tools.doc_parser import read_sheet


def _classify_files(data_dir):
    """扫描目录，按文件名分类到 8 种数据源"""
    files = [f for f in os.listdir(data_dir) if f.endswith(".xlsx")]

    mapping = {
        "pms_report": None, "pos": None,
        "wechat_ar": None, "alipay_ar": None,
        "yfd_wechat_ar": None, "yfd_alipay_ar": None,
        "yfd_wechat_bank": None, "yfd_alipay_bank": None,
    }

    for f in files:
        fl = f.lower()
        if "pms报表" in fl:
            mapping["pms_report"] = f
        elif "yfd" in fl and "银行流水" in fl:
            if "wechat" in fl or "微信" in fl:
                mapping["yfd_wechat_bank"] = f
            elif "alipay" in fl or "支付宝" in fl:
                mapping["yfd_alipay_bank"] = f
        elif "yfd" in fl and "应收后台" in fl:
            if "wechat" in fl or "微信" in fl:
                mapping["yfd_wechat_ar"] = f
            elif "alipay" in fl or "支付宝" in fl:
                mapping["yfd_alipay_ar"] = f
        elif "pos" in fl or ("银行流水" in fl and "yfd" not in fl):
            mapping["pos"] = f
        elif "应收后台" in fl and "yfd" not in fl:
            if "wechat" in fl or "微信" in fl:
                mapping["wechat_ar"] = f
            elif "alipay" in fl or "支付宝" in fl:
                mapping["alipay_ar"] = f

    return mapping


def _group_by_key(records, key_fn):
    """通用分组工具"""
    groups = {}
    for r in records:
        k = key_fn(r)
        if k not in groups:
            groups[k] = []
        groups[k].append(r)
    return groups


def batch_card_recon(data_dir=None):
    """批量信用卡对账：自动配对 PMS报表 + PMS应收后台 + 银行流水"""
    if data_dir is None:
        data_dir = os.path.join(BASE_DIR, "data", "清远", "信用卡对账")
    if not os.path.exists(data_dir):
        return f"错误：数据目录不存在: {data_dir}"

    files = _classify_files(data_dir)

    # 解析所有数据源
    pms_groups = (
        _read_pms_report(os.path.join(data_dir, files["pms_report"]))
        if files["pms_report"] else {}
    )
    pos_records = (
        _read_pos_statement(os.path.join(data_dir, files["pos"]))
        if files["pos"] else []
    )

    ar_records = []
    for key in ("wechat_ar", "alipay_ar", "yfd_wechat_ar", "yfd_alipay_ar"):
        if files[key]:
            ar_records.extend(_read_pms_ar_backend(os.path.join(data_dir, files[key])))

    yfd_bank_records = []
    for key in ("yfd_wechat_bank", "yfd_alipay_bank"):
        if files[key]:
            yfd_bank_records.extend(read_yfd_bank(os.path.join(data_dir, files[key])))

    # 按通道分组
    pos_by_type = _group_by_key(pos_records, lambda r: r["pay_type"])
    ar_by_channel = _group_by_key(ar_records, lambda r: r["channel"])
    yfd_by_channel = _group_by_key(yfd_bank_records, lambda r: YFD_TYPE_MAP.get(r["tx_type"], r["tx_type"]))

    # 执行对账
    recon_results = []

    # WECHAT / ALIPAY：PMS报表 vs POS银行流水
    for pay_type, channel in PAY_TYPE_TO_CHANNEL.items():
        pms_txs = pms_groups.get(pay_type, [])
        bank_txs = pos_by_type.get(pay_type, [])
        if pms_txs or bank_txs:
            recon_results.append(_reconcile_channel(channel, pms_txs, bank_txs))

    # YFD：PMS应收 vs YFD银行流水
    for channel in ("YFD_WECHAT", "YFD_ALIPAY"):
        pms_txs = ar_by_channel.get(channel, [])
        bank_txs = yfd_by_channel.get(channel, [])
        if pms_txs or bank_txs:
            recon_results.append(_reconcile_channel(channel, pms_txs, bank_txs))

    return _generate_recon_report(recon_results)
def _detect_file_type(path):
    """检测文件类型: 'pms_report' | 'pos_statement' | 'card_statement' | 'unknown'"""
    from tools.doc_parser import _open, _get_headers
    wb, ws = _open(path)
    h1_str = " ".join(str(h) for h in _get_headers(ws, 1) if h)
    if "付款代码" in h1_str and "付款描述" in h1_str:
        wb.close()
        return "pms_report"
    h3_str = " ".join(str(h) for h in _get_headers(ws, 3) if h)
    if "支付类型" in h3_str and "客户实付金额" in h3_str:
        wb.close()
        return "pos_statement"
    if "支付类型" in h1_str and "客户实付金额" in h1_str:
        wb.close()
        return "pos_statement"
    if "卡号" in h1_str or "card" in h1_str.lower():
        wb.close()
        return "card_statement"
    wb.close()
    return "unknown"

def _normalize_pay_type(pay_type, source):
    """统一支付方式名称：PMS '微信' -> '微信支付'，其他保持一致"""
    if source == "pms":
        mapping = {"微信": "微信支付", "支付宝": "支付宝支付"}
        return mapping.get(pay_type, pay_type)
    return pay_type

def _flatten_pms_groups(pms_groups):
    """将 PMS报表分组展平为单通道模式可用的交易列表"""
    transactions = []
    for pay_type, txs in pms_groups.items():
        for tx in txs:
            transactions.append({
                "amount": tx["amount"],
                "pay_type": pay_type,
                "bill_no": tx.get("bill_no", ""),
                "raw": tx.get("raw", {}),
            })
    return transactions

@tool
def credit_card_recon(bank_statement_path: str = "", pms_card_path: str = "") -> str:
    """信用卡对账：支持批量模式(无参数)和单通道模式。
    批量模式自动读取 data/清远/信用卡对账 目录下所有文件并生成汇总。
    单通道模式自动检测文件类型(PMS报表/POS流水/卡对账单)，按支付方式分组对账。
    """
    if not bank_statement_path and not pms_card_path:
        return batch_card_recon()

    for p in (bank_statement_path, pms_card_path):
        if not os.path.exists(p):
            return f"error: {p}"

    bank_type = _detect_file_type(bank_statement_path)
    pms_type = _detect_file_type(pms_card_path)

    # 根据文件类型选择解析器
    if pms_type == "pms_report":
        pms_groups = _read_pms_report(pms_card_path)
        pms_txs = _flatten_pms_groups(pms_groups)
        for tx in pms_txs:
            tx["pay_type"] = _normalize_pay_type(tx["pay_type"], "pms")
    elif pms_type == "pos_statement":
        pms_txs = [{"amount": r["amount"], "pay_type": r["pay_type"], "raw": r} for r in _read_pos_statement(pms_card_path)]
    else:
        def _parse_date(val):
            if isinstance(val, datetime):
                return val
            if isinstance(val, str) and val.strip():
                for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
                    try:
                        return datetime.strptime(val.strip(), fmt)
                    except ValueError:
                        pass
            return None

        headers, rows = read_sheet(pms_card_path)
        pms_txs = []
        for r in rows:
            date_val = r.get("日期", r.get("交易日期", r.get("date", "")))
            amount_val = r.get("金额", r.get("交易金额", r.get("amount", 0)))
            try:
                amount = float(amount_val or 0)
            except (ValueError, TypeError):
                continue
            card_val = r.get("卡号", r.get("card", ""))
            pms_txs.append({
                "date": _parse_date(date_val),
                "amount": amount,
                "card": str(card_val).strip()[-4:],
                "raw": r,
            })

    if bank_type == "pos_statement":
        pos_records = _read_pos_statement(bank_statement_path)
        bank_txs = [{"amount": r["amount"], "pay_type": r["pay_type"], "fee": r["fee"], "raw": r} for r in pos_records]
    elif bank_type == "pms_report":
        bank_groups = _read_pms_report(bank_statement_path)
        bank_txs = _flatten_pms_groups(bank_groups)
    else:
        def _parse_date(val):
            if isinstance(val, datetime):
                return val
            if isinstance(val, str) and val.strip():
                for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
                    try:
                        return datetime.strptime(val.strip(), fmt)
                    except ValueError:
                        pass
            return None

        headers, rows = read_sheet(bank_statement_path)
        bank_txs = []
        for r in rows:
            date_val = r.get("日期", r.get("交易日期", r.get("date", "")))
            amount_val = r.get("金额", r.get("交易金额", r.get("amount", 0)))
            try:
                amount = float(amount_val or 0)
            except (ValueError, TypeError):
                continue
            card_val = r.get("卡号", r.get("card", ""))
            bank_txs.append({
                "date": _parse_date(date_val),
                "amount": amount,
                "card": str(card_val).strip()[-4:],
                "raw": r,
            })

    # 按支付方式分组后逐通道对账
    pms_by_type = _group_by_key(pms_txs, lambda r: r.get("pay_type", "未知"))
    bank_by_type = _group_by_key(bank_txs, lambda r: r.get("pay_type", "未知"))

    all_types = set(pms_by_type.keys()) | set(bank_by_type.keys())
    recon_results = []
    for pay_type in sorted(all_types):
        pms = pms_by_type.get(pay_type, [])
        bank = bank_by_type.get(pay_type, [])
        if pms or bank:
            recon_results.append(_reconcile_channel(pay_type, pms, bank))

    return _generate_recon_report(recon_results)


if __name__ == "__main__":
    result = batch_card_recon()
    print(result)