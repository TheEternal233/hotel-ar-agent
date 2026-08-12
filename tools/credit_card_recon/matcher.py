"""信用卡对账：对账核心逻辑

对每种付款方式：
1. 数量匹配 —— 对比 PMS 与 POS 的交易笔数是否一致；
2. 金额对比 —— 对比 PMS 与 POS 的金额合计，相同则对平，不同则计算差额；
3. 逐笔配对 —— 同金额分组配对，找出未匹配明细供差异表展示。
"""
import logging
from collections import defaultdict

from tools.credit_card_recon.constants import AMOUNT_TOLERANCE

logger=logging.getLogger(__name__)
def _safe_amount(tx):
    """安全获取交易金额，非数字类型返回 None 并告警"""
    raw=tx.get("amount")
    try:
        return float(raw) if raw is not None else 0.0
    except (ValueError, TypeError):
        logger.warning("对账匹配时遇到非数字金额: %r, 账单号=%s", raw, tx.get("bill_no", "?"))
        return None
def _match_by_amount(pms_txs, bank_txs):
    """同金额分组配对：先按金额分组，同金额多笔按顺序配对。

    Returns:
        (matched_pairs, unmatched_pms, unmatched_bank)
    """
    def group_by_amount(txs):
        groups = defaultdict(list)
        for t in txs:
            amt=_safe_amount(t)
            if amt is None:
                continue
            key = int(round(amt*100))
            groups[key].append(t)
        return groups

    pms_groups = group_by_amount(pms_txs)
    bank_groups = group_by_amount(bank_txs)

    matched = []
    unmatched_pms = []
    unmatched_bank = []

    # 第 1 轮：精确金额匹配
    for amount, pms_list in list(pms_groups.items()):
        bank_list = bank_groups.get(amount, [])
        match_count = min(len(pms_list), len(bank_list))
        for i in range(match_count):
            matched.append({"pms": pms_list[i], "bank": bank_list[i], "amount": amount})
        for i in range(match_count, len(pms_list)):
            unmatched_pms.append(pms_list[i])
        for i in range(match_count, len(bank_list)):
            unmatched_bank.append(bank_list[i])
        del pms_groups[amount]
        if amount in bank_groups:
            del bank_groups[amount]

    # 剩余未匹配（金额组在对方完全不存在）
    for pms_list in pms_groups.values():
        unmatched_pms.extend(pms_list)
    for bank_list in bank_groups.values():
        unmatched_bank.extend(bank_list)

    return matched, unmatched_pms, unmatched_bank


def _reconcile_channel(channel, pms_txs, bank_txs):
    """单个付款方式的对账逻辑。

    流程：
      数量匹配 → 金额对比 → 计算差额 → 逐笔配对找差异明细。

    Returns:
        dict: channel, pms_count, bank_count, count_match,
              pms_total, bank_total, diff, amount_match, balanced,
              matched, unmatched_pms, unmatched_bank
    """
    if not pms_txs and not bank_txs:
        logger.info("渠道[%s] PMS与POS均无数据，跳过对账", channel)

    # 1) 数量（交易笔数）
    pms_count = len(pms_txs)
    bank_count = len(bank_txs)
    count_match = pms_count == bank_count

    # 2) 金额合计
    pms_total = round(sum(_safe_amount(t) or 0 for t in pms_txs), 2)
    bank_total = round(sum(_safe_amount(t) or 0 for t in bank_txs), 2)
    bank_fees = round(sum(t.get("fee", 0) for t in bank_txs if isinstance(t.get("fee"),(int,float))), 2)

    # 3) 金额差额（PMS - POS），相同则对平
    diff = round(pms_total - bank_total, 2)
    amount_match = abs(diff) <= AMOUNT_TOLERANCE

    # 4) 逐笔配对（同金额分组），找出未匹配明细
    matched, unmatched_pms, unmatched_bank = _match_by_amount(pms_txs, bank_txs)

    # 逐笔匹配：不存在任何未配对的短款/长款
    all_matched = (len(unmatched_pms) == 0 and len(unmatched_bank) == 0)

    # 完全对平必须同时满足：数量一致 + 金额一致 + 逐笔全部配对成功
    # （避免「数量和总额都对得上，但实际是单笔错配互相抵消」的假对平）
    balanced = count_match and amount_match and all_matched

    return {
        "channel": channel,
        "pms_count": pms_count,
        "bank_count": bank_count,
        "count_match": count_match,
        "pms_total": pms_total,
        "bank_total": bank_total,
        "bank_fees": bank_fees,
        "diff": diff,
        "amount_match": amount_match,
        "all_matched": all_matched,
        "matched_count": len(matched),
        "unmatched_pms_count": len(unmatched_pms),
        "unmatched_bank_count": len(unmatched_bank),
        "balanced": balanced,
        "matched": matched,
        "unmatched_pms": unmatched_pms,
        "unmatched_bank": unmatched_bank,
    }
