import bisect
from collections import defaultdict

from tools.ar_recon.constants import (
    AMOUNT_TOLERANCE, MAX_AMOUNT_DIFF, DIFF_TOLERANCE,
    STATUS_MATCH, STATUS_DIFF, STATUS_OTA_ONLY, STATUS_PMS_ONLY,
)
from tools.doc_parser import OTA_CHANNEL_MAPPINGS
from utils.common_func import _norm_amount, _norm_orderno


# =====================================================================
# 索引构建函数（一次性预处理，后续查询 O(1)）
# =====================================================================

def _build_pms_order_index(pms_list):
    """按 ext_order / order 构建 PMS 索引"""
    by_ext, by_order = {}, {}
    for i, p in enumerate(pms_list):
        ext = _norm_orderno(p.get("ext_order", ""))
        od = _norm_orderno(p.get("order", ""))

        if ext:
            by_ext.setdefault(ext, []).append(i)
        if od:
            by_order.setdefault(od, []).append(i)

    return by_ext, by_order


def _build_pms_identify_index(pms_list):
    """构建 identify 模糊匹配索引 + 金额索引

    Returns:
        identify_index: dict[str, list[int]]
            key 为完整的 ext_order / order 字符串，value 为索引列表
        amount_index: dict[int, list[int]]
            key 为金额(分)，value 为索引列表
        sorted_amounts: list[tuple[int, int]]
            按金额(分)排序的 (amount_key, index) 列表，用于 bisect 范围查询
    """
    identify_index = defaultdict(list)
    amount_index = defaultdict(list)
    sorted_amounts = []  # (amount_key, index)

    for i, p in enumerate(pms_list):
        ext = _norm_orderno(p.get("ext_order", ""))
        od = _norm_orderno(p.get("order", ""))
        amt = _norm_amount(p.get("amount", 0))

        if ext:
            identify_index[ext].append(i)
        if od and od != ext:
            identify_index[od].append(i)

        if amt > 0:
            key = int(round(amt * 100))
            amount_index[key].append(i)
            sorted_amounts.append((key, i))

    sorted_amounts.sort(key=lambda x: x[0])
    return identify_index, amount_index, sorted_amounts


# =====================================================================
# 匹配函数（基于索引，避免 O(n) 线性扫描）
# =====================================================================

def _match_by_order_id(oid, amt, pms_list, by_ext, by_order, used, amount_tol=AMOUNT_TOLERANCE):
    """按订单号匹配：先金额一致，再仅订单号"""
    if not oid:
        return -1
    candidates = by_ext.get(oid, [])
    # 第一轮：金额一致
    for ci in candidates:
        if ci in used:
            continue
        if abs(amt - _norm_amount(pms_list[ci].get("amount", 0))) < amount_tol:
            return ci
    # 第二轮：仅订单号
    for ci in candidates:
        if ci in used:
            continue
        return ci
    return -1


def _match_by_identify_fast(identify, amt, pms_list, used,
                            identify_index, amount_index, sorted_amounts,
                            amount_tol=AMOUNT_TOLERANCE):
    """按 identify_no 模糊匹配（索引加速版）

    策略：
        1. 精确匹配：identify 作为完整 key 查索引
        2. Fallback：在金额相近的记录中做子串匹配（bisect 范围查询替代逐 key 扫描）
    """
    if not identify:
        return -1

    # --- 第一轮：精确匹配 + 金额一致 ---
    candidates = identify_index.get(identify, [])
    for ci in candidates:
        if ci in used:
            continue
        if abs(amt - _norm_amount(pms_list[ci].get("amount", 0))) < amount_tol:
            return ci

    # --- 第二轮：精确匹配 + 仅 identify ---
    for ci in candidates:
        if ci in used:
            continue
        return ci

    # --- 第三轮：金额相近记录中子串匹配 ---
    # 使用 bisect 在有序金额列表上做范围查询，替代逐 key 扫描
    amt_key = int(round(amt * 100))
    max_diff_key = int(round(MAX_AMOUNT_DIFF * 100))
    lo_key = amt_key - max_diff_key
    hi_key = amt_key + max_diff_key

    # bisect 找到范围边界
    lo = bisect.bisect_left(sorted_amounts, (lo_key, -1))
    hi = bisect.bisect_right(sorted_amounts, (hi_key, float('inf')))

    # 去重保持顺序
    seen = set()
    for _, ci in sorted_amounts[lo:hi]:
        if ci in seen or ci in used:
            continue
        seen.add(ci)
        ext = _norm_orderno(pms_list[ci].get("ext_order", ""))
        od = _norm_orderno(pms_list[ci].get("order", ""))
        if identify in ext or identify in od:
            if abs(amt - _norm_amount(pms_list[ci].get("amount", 0))) < amount_tol:
                return ci

    # --- 第四轮：子串匹配，不要求金额一致 ---
    for _, ci in sorted_amounts[lo:hi]:
        if ci in used:
            continue
        ext = _norm_orderno(pms_list[ci].get("ext_order", ""))
        od = _norm_orderno(pms_list[ci].get("order", ""))
        if identify in ext or identify in od:
            return ci

    return -1


def _match_by_amount_fast(amt, pms_list, used, amount_index, sorted_amounts, max_diff=MAX_AMOUNT_DIFF):
    """无订单号时按金额模糊匹配（索引加速版）

    使用 bisect 在有序金额列表上做范围查询，替代逐 key 扫描。
    """
    if amt <= 0:
        return -1

    target_key = int(round(amt * 100))
    max_diff_key = int(round(max_diff * 100))
    lo_key = target_key - max_diff_key
    hi_key = target_key + max_diff_key

    # bisect 找到范围边界
    lo = bisect.bisect_left(sorted_amounts, (lo_key, -1))
    hi = bisect.bisect_right(sorted_amounts, (hi_key, float('inf')))

    best_i, best_d = -1, float("inf")

    for _, ci in sorted_amounts[lo:hi]:
        if ci in used:
            continue
        pms_amt = _norm_amount(pms_list[ci].get("amount", 0))
        if pms_amt <= 0:
            continue
        d = abs(amt - pms_amt)
        if d < max_diff and d < best_d:
            best_d = d
            best_i = ci

    return best_i


def _make_result(status, ota, pms, ota_amt, pms_amt, ota_order, pms_ext_order):
    """构建单条匹配结果"""
    return {
        "status": status,
        "ota": ota,
        "pms": pms,
        "ota_amount": ota_amt,
        "pms_amount": pms_amt,
        "diff": round(ota_amt - pms_amt, 2),
        "ota_order": ota_order,
        "pms_ext_order": pms_ext_order,
    }


def _append_unmatched_pms(results, pms_list, used):
    """追加未匹配的 PMS 记录"""
    for i, p in enumerate(pms_list):
        if i not in used:   # 不在used->未被任何OTA匹配到
            pms_amt = _norm_amount(p.get("amount", 0))
            results.append({
                "status": STATUS_PMS_ONLY,
                "ota": None,
                "pms": p,
                "ota_amount": 0,
                "pms_amount": pms_amt,
                "diff": pms_amt,
                "ota_order": "",
                "pms_ext_order": _norm_orderno(p.get("ext_order", "")),
            })


def _calc_stats(results, total_ota=None, total_pms=None):
    """从结果列表计算统计"""
    return {
        "total_ota": total_ota if total_ota is not None else sum(1 for r in results if r["ota"] is not None),
        "total_pms": total_pms if total_pms is not None else sum(1 for r in results if r["pms"] is not None),
        "match": sum(1 for r in results if r["status"] == STATUS_MATCH),
        "diff": sum(1 for r in results if r["status"] == STATUS_DIFF),
        "ota_only": sum(1 for r in results if r["status"] == STATUS_OTA_ONLY),
        "pms_only": sum(1 for r in results if r["status"] == STATUS_PMS_ONLY),
    }


def _build_amount_counter(records, amount_key, extra_key):
    """按金额统计出现次数，并收集附加字段（用于 F&B 聚合）"""
    counts, extras, total = {}, {}, 0.0
    for r in records:
        val = _norm_amount(r.get(amount_key, 0))
        if val == 0:
            continue
        counts[val] = counts.get(val, 0) + 1
        extras.setdefault(val, []).append(str(r.get(extra_key, "") or ""))
        total += val
    return counts, extras, total



def _match_ota_rezen(ota_records, rezen_records, channel_name):
    oci = OTA_CHANNEL_MAPPINGS.get(channel_name, {})
    oid_col = oci.get("order_id_col", "order_id")
    amt_col = oci.get("amount_col", "amount")

    rezen_by_ext, rezen_by_order = _build_pms_order_index(rezen_records)
    _, rezen_amount_index, rezen_sorted_amounts = _build_pms_identify_index(rezen_records)
    rezen_matched = set()
    results = []

    for ota in ota_records:
        oid = _norm_orderno(ota.get(oid_col, ""))
        oamt = _norm_amount(ota.get(amt_col, 0))

        # 先走订单号
        ri = _match_by_order_id(oid, oamt, rezen_records, rezen_by_ext, rezen_by_order, rezen_matched)

        if ri < 0 and not oid and oamt > 0:
            # 没有订单号、也没有识别号，只能靠金额。
            ri = _match_by_amount_fast(oamt, rezen_records, rezen_matched, rezen_amount_index, rezen_sorted_amounts)

        if ri >= 0:
            # 匹配成功->比较金额
            rezen_matched.add(ri)
            ramt = _norm_amount(rezen_records[ri].get("amount", 0))
            diff = round(oamt - ramt, 2)
            status = STATUS_MATCH if abs(diff) < DIFF_TOLERANCE else STATUS_DIFF
            results.append(_make_result(
                status, ota, rezen_records[ri], oamt, ramt, oid,
                _norm_orderno(rezen_records[ri].get("ext_order", ""))
            ))
        else:
            # 失败->ota_only
            results.append(_make_result(STATUS_OTA_ONLY, ota, None, oamt, 0, oid, ""))

    _append_unmatched_pms(results, rezen_records, rezen_matched)
    stats = _calc_stats(results,len(ota_records),len(rezen_records))
    return results, stats


def _match_ota_rezen_fnb(ota_records, rezen_records, channel_name):
    oci = OTA_CHANNEL_MAPPINGS.get(channel_name, {})
    price_col = oci.get("amount_col", "sell_price")

    ota_counts, ota_vouchers, ota_total = _build_amount_counter(ota_records, price_col, "voucher_no")
    pms_counts, pms_bills, pms_total = _build_amount_counter(rezen_records, "amount", "bill_no")

    # 收集所有金额，按容差确定统一基准
    # O(n log n) 排序后线性扫描合并，替代原 O(n²) 的逐组比较
    all_amounts = sorted(set(ota_counts.keys()) | set(pms_counts.keys()))
    price_groups = []  # [(基准价格, [相近价格列表]), ...]

    for amt in all_amounts:
        if price_groups and abs(amt - price_groups[-1][0]) < AMOUNT_TOLERANCE:
            price_groups[-1][1].append(amt)
        else:
            price_groups.append((amt, [amt]))

    results = []
    stats = {
        "total_ota": len(ota_records),
        "total_pms": len(rezen_records),
        "match": 0, "diff": 0, "ota_only": 0, "pms_only": 0,
        "ota_amount_total": round(ota_total, 2),
        "pms_amount_total": round(pms_total, 2),
    }

    for base, members in price_groups:
        ota_cnt = sum(ota_counts.get(m, 0) for m in members)
        pms_cnt = sum(pms_counts.get(m, 0) for m in members)

        # 收集券号/账单号
        ota_vouchers_list = []
        pms_bills_list = []
        for m in members:
            ota_vouchers_list.extend(ota_vouchers.get(m, []))
            pms_bills_list.extend(pms_bills.get(m, []))

        diff_cnt = ota_cnt - pms_cnt
        ota_amt_total = round(base * ota_cnt, 2)
        pms_amt_total = round(base * pms_cnt, 2)
        diff_amt = round(ota_amt_total - pms_amt_total, 2)

        if ota_cnt == pms_cnt and ota_cnt > 0:
            status = STATUS_MATCH
            stats["match"] += 1
        elif ota_cnt > 0 and pms_cnt == 0:
            status = STATUS_OTA_ONLY
            stats["ota_only"] += 1
        elif pms_cnt > 0 and ota_cnt == 0:
            status = STATUS_PMS_ONLY
            stats["pms_only"] += 1
        else:
            status = STATUS_DIFF
            stats["diff"] += 1

        results.append({
            "status": status,
            "price": base,
            "ota_count": ota_cnt,
            "pms_count": pms_cnt,
            "diff_count": diff_cnt,
            "ota_amount_total": ota_amt_total,
            "pms_amount_total": pms_amt_total,
            "diff_amount": diff_amt,
            "ota_vouchers": ", ".join(v for v in ota_vouchers_list if v),
            "pms_bills": ", ".join(b for b in pms_bills_list if b),
        })

    return results, stats


def match_xiangminiao(ota_list, pms_list, card_list=None):
    # 一次性构建所有索引（O(m) 预处理）
    pms_by_ext, pms_by_order = _build_pms_order_index(pms_list)
    pms_identify_index, pms_amount_index, pms_sorted_amounts = _build_pms_identify_index(pms_list)

    card_map = {}
    if card_list:
        for c in card_list:
            oid = _norm_orderno(c.get("order_id", ""))
            if oid:
                card_map[oid] = c

    used = set()
    results = []

    for ota in ota_list:
        oid = _norm_orderno(ota.get("order_id", ""))
        identify = _norm_orderno(ota.get("identify_no", ""))
        pay_type = str(ota.get("pay_type", ""))
        settle_amt = _norm_amount(ota.get("settle_amount", 0))

        # 金额计算逻辑（保持原有）
        if "储值" in pay_type or settle_amt == 0:
            amt = _norm_amount(ota.get("card_pay_amount", 0))
            if amt == 0 and oid in card_map:
                amt = _norm_amount(card_map[oid].get("card_amount", 0))
            if amt == 0:
                amt = settle_amt
            if amt == 0:
                amt = _norm_amount(ota.get("actual_amount", 0))
        else:
            amt = settle_amt
            if amt == 0:
                amt = _norm_amount(ota.get("actual_settle", 0))

        idx = _match_by_order_id(oid, amt, pms_list, pms_by_ext, pms_by_order, used)

        if idx < 0 and identify:
            idx = _match_by_identify_fast(
                identify, amt, pms_list, used,
                pms_identify_index, pms_amount_index, pms_sorted_amounts
            )

        if idx < 0 and amt > 0 and not oid and not identify:
            idx = _match_by_amount_fast(amt, pms_list, used, pms_amount_index, pms_sorted_amounts)

        if idx >= 0:
            used.add(idx)
            pms_amt = _norm_amount(pms_list[idx].get("amount", 0))
            diff = round(amt - pms_amt, 2)
            is_card_full = ("储值" in pay_type and pms_amt == 0 and amt > 0)
            status = STATUS_MATCH if (abs(diff) < DIFF_TOLERANCE or is_card_full) else STATUS_DIFF
            results.append(_make_result(
                status, ota, pms_list[idx], amt, pms_amt, oid,
                _norm_orderno(pms_list[idx].get("ext_order", ""))
            ))
        else:
            results.append(_make_result(STATUS_OTA_ONLY, ota, None, amt, 0, oid, ""))

    _append_unmatched_pms(results, pms_list, used)
    return results, _calc_stats(results, len(ota_list), len(pms_list))