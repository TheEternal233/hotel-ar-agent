"""信用卡对账：数据解析器

读取 PMS报表 与 POS机银行流水，按 4 种规范付款方式
（微信、支付宝、OTA卡、预付卡）分组。
挂应收、挂房账、挂团队、OC、ENT、YFD 等付款方式不统计。
"""
import logging

from tools.doc_parser import read_sheet
from tools.credit_card_recon.constants import normalize_payment

logger=logging.getLogger(__name__)

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
    skipped_amt=0
    for r in rows:
        raw = r.get("付款代码", "")
        if isinstance(raw, (int, float)):
            code = str(int(raw))
        else:
            code = str(raw).strip() if raw else ""
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
            skipped_amt+=1
            logger.warning(
                "PMS报表 金额解析失败，账单号=%s,原始金额值=%r",
                r.get("账单号","?"),amt_val,
            )
            continue
        groups.setdefault(method, []).append({
            "amount": amount,
            "bill_no": str(r.get("账单号", "")),
            "raw": r,
        })
    if skipped_amt:
        logger.warning("PMS报表 因金额解析失败跳过了 %d 条记录",skipped_amt)
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
    skipped_amt=0
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
        try:
            amount = float(r.get("客户实付金额", 0) or 0)
            fee = float(r.get("手续费金额", 0) or 0)
            net = float(r.get("入账金额", 0) or 0)
        except (ValueError, TypeError):
            skipped_amt+=1
            logger.warning(
                "POS流水 金额解析失败，支付类型=%s,客户实付=%r,手续费=%r,入账=%r",
                pay_type,
                r.get("客户实付金额"),
                r.get("手续费金额"),
                r.get("入账金额"),
            )
            continue
        groups.setdefault(method, []).append({
            "amount": amount,
            "fee": fee,
            "net": net,
            "tx_time": r.get("交易时间"),
            "raw": r,
        })
    if skipped_amt:
        logger.warning("POS流水 因金额解析失败跳过了 %d 条记录",skipped_amt)
    return groups

def _read_yfd_pms(path,channel_keyword):
    """读取YFD PMS应收后台，按渠道关键词过滤借方记录

    YFD PMS特征
    - 表头在第一行
    - 第 2 行通常是重复表头，靠「类型」列过滤排除。
    - 只保留「借方」交易（贷方为退款/调账，不参与对账）。
    - 按「姓名/描述」中的渠道关键词过滤（如 "YFD 支付宝"、"YFD微信"）。

    Returns:
        list: [{"amount", "bill_no", "raw"}, ...]

    """
    headers,rows=read_sheet(path,header_row=1)
    txs=[]
    skipped_amt=0
    for r in rows:
        tx_type = str(r.get("类型", "")).strip()
        if tx_type !="借方":
            continue
        desc_val = r.get("姓名/描述") or r.get("姓名 / 描述")
        desc = str(desc_val).strip() if desc_val else ""
        desc_nospace=desc.replace(" ","")
        keyword_nospace=channel_keyword.replace(" ","")
        if keyword_nospace not in desc_nospace:
            continue

        amt_val=r.get("金额",0)
        try:
            amount = float(amt_val) if amt_val is not None else 0
        except (ValueError, TypeError):
            skipped_amt+=1
            logger.warning(
                "YFD PMS(%s) 金额解析失败，账单号=%s,原始金额值=%r",
                channel_keyword,
                r.get("账单号","?"),
                amt_val,
            )
            continue
        txs.append({
            "amount": amount,
            "bill_no": str(r.get("账单号","")),
            "raw": r,
        })
    if skipped_amt:
        logger.warning("YFD PMS(%s) 因金额解析失败跳过了 %d 条记录",channel_keyword,skipped_amt)
    return txs




def _read_yfd_bank(path):
    """
    读取 YFD 银行流水（ALIPAY / WECHAT 通用）。

    YFD 银行流水特征：
    - 表头在第 5 行（前 4 行为文件信息/商户信息）。
    - 数据行以「文件信息」列 = "RD" 为标识。
    - 列名可能带序号前缀（如 "10.金额"），需模糊匹配。

    Returns:
        list: [{"amount", "fee", "net", "tx_time", "raw"}, ...]
    """

    headers,rows = read_sheet(path,header_row=5)

    #预扫描列名，建立模糊映射
    amount_col=fee_col=net_col=tx_time_col=file_info_col=None
    for h in headers:
        hs=str(h).strip()
        if not hs:
            continue
        if "文件信息" in hs:
            file_info_col=h
        elif "金额" in hs and "结算" not in hs and "佣金" not in hs:
            amount_col=h
        elif "服务佣金" in hs:
            fee_col=h
        elif "结算金额" in hs:
            net_col=h
        elif "交易时间" in hs:
            tx_time_col=h

    missing_cols=[]
    if not amount_col:
        missing_cols.append("金额")
    if not net_col:
        missing_cols.append("结算金额")
    if missing_cols:
        logger.warning(
            "YFD银行流水 缺少关键列：%s,表头=%s",
            ",".join(missing_cols),headers
        )
    txs=[]
    skipped_amt=0
    for r in rows:
        #只保留RD数据行
        if file_info_col:
            if str(r.get(file_info_col,"")).strip()!="RD":
                continue
        else:
            #兜底，取第一行判断
            first_col=next(iter(r.keys())) if r else None
            if first_col and str(r.get(first_col,"")).strip()!="RD":
                continue

        try:
            amount = float(r.get(amount_col,0)) if amount_col else 0
            fee=float(r.get(fee_col,0)) if fee_col else 0
            net=float(r.get(net_col,0)) if net_col else 0
        except (ValueError, TypeError):
            skipped_amt+=1
            logger.warning(
                "YFD银行流水 金额解析失败,金额=%r，佣金=%r，结算=%r",
                r.get(amount_col) if amount_col else "N/A",
                r.get(fee_col) if fee_col else "N/A",
                r.get(net_col) if net_col else "N/A",
            )
            continue

        txs.append({
            "amount": amount,
            "fee": fee,
            "net": net,
            "tx_time":str(r.get(tx_time_col,"")) if tx_time_col else "",
            "raw": r,
        })
    if skipped_amt:
        logger.warning("YFD银行流水 因金额解析失败跳过了 %d 条记录", skipped_amt)
    return txs