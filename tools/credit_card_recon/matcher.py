"""信用卡对账：通道分类 + 借方贷方分离 + 金额配对 + 对账核心"""

from collections import defaultdict


def classify_channel(name: str) -> str:
    """从 PMS应收后台的姓名/描述字段推断支付通道"""
    name = name.upper()
    if "YFD" in name:
        if "微信" in name or "WECHAT" in name:
            return "YFD_WECHAT"
        if "支付宝" in name or "ALIPAY" in name:
            return "YFD_ALIPAY"
    if "微信" in name or "WECHAT" in name:
        return "WECHAT"
    if "支付宝" in name or "ALIPAY" in name:
        return "ALIPAY"
    return "UNKNOWN"


def split_debit_credit(records):
    """分离借方（收款）和贷方（退款）"""
    charges = [r for r in records if r.get("type") == "借方"]
    refunds = [r for r in records if r.get("type") == "贷方"]
    return charges, refunds


def _match_by_amount(pms_txs, bank_txs, tolerance=0.01):
    """同金额分组配对算法。先精确匹配，同金额多笔时按顺序配对。

    Returns: (matched_pairs, unmatched_pms, unmatched_bank)
    """
    def group_by_amount(txs):
        groups = defaultdict(list)
        for t in txs:
            key = round(float(t.get("amount", 0)), 2)
            groups[key].append(t)
        return groups

    pms_groups = group_by_amount(pms_txs)
    bank_groups = group_by_amount(bank_txs)

    matched = []
    unmatched_pms = []
    unmatched_bank = []

    # 第1轮：精确金额匹配
    for amount, pms_list in list(pms_groups.items()):
        bank_list = bank_groups.get(amount, [])
        match_count = min(len(pms_list), len(bank_list))
        for i in range(match_count):
            matched.append({"pms": pms_list[i], "bank": bank_list[i], "amount": amount})
        # 剩余未匹配的
        for i in range(match_count, len(pms_list)):
            unmatched_pms.append(pms_list[i])
        for i in range(match_count, len(bank_list)):
            unmatched_bank.append(bank_list[i])
        # 清空已处理
        del pms_groups[amount]
        if amount in bank_groups:
            del bank_groups[amount]

    # 剩余未匹配（金额组完全不存在于对方）
    for pms_list in pms_groups.values():
        unmatched_pms.extend(pms_list)
    for bank_list in bank_groups.values():
        unmatched_bank.extend(bank_list)

    return matched, unmatched_pms, unmatched_bank


def _reconcile_channel(channel, pms_txs, bank_txs):
    """单个通道的对账逻辑

    Returns: dict with channel, pms_total, bank_total, diff, counts, match results
    """
    # Step 2: 金额聚合对比
    pms_total = sum(t.get("amount", 0) for t in pms_txs)
    bank_total = sum(t.get("amount", 0) for t in bank_txs)
    bank_fees = sum(t.get("fee", 0) for t in bank_txs)

    diff = round(pms_total - bank_total, 2)
    is_balanced = abs(diff) <= 0.01

    # Step 3: 条数校验
    pms_count = len(pms_txs)
    bank_count = len(bank_txs)
    count_match = pms_count == bank_count

    # 逐笔匹配（同金额分组配对）
    matched, unmatched_pms, unmatched_bank = _match_by_amount(pms_txs, bank_txs)

    return {
        "channel": channel,
        "pms_total": pms_total,
        "bank_total": bank_total,
        "diff": diff,
        "bank_fees": bank_fees,
        "pms_count": pms_count,
        "bank_count": bank_count,
        "count_match": count_match,
        "matched": matched,
        "unmatched_pms": unmatched_pms,
        "unmatched_bank": unmatched_bank,
        "balanced": is_balanced and count_match,
    }