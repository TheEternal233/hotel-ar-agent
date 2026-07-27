from tools.doc_parser import OTA_CHANNEL_MAPPINGS
from utils.common_func import _norm_amount, _norm_orderno


def _match_ota_rezen(ota_records, rezen_records, channel_name):
    oci = OTA_CHANNEL_MAPPINGS.get(channel_name, {})
    oid_col = oci.get("order_id_col", "order_id")
    amt_col = oci.get("amount_col", "amount")

    rezen_by_ext = {}
    rezen_by_order = {}
    for i, r in enumerate(rezen_records):
        eo = _norm_orderno(r.get("ext_order", ""))
        od = _norm_orderno(r.get("order", ""))
        if eo:
            rezen_by_ext.setdefault(eo, []).append(i)
        if od:
            rezen_by_order.setdefault(od, []).append(i)

    rezen_matched = set()
    results = []
    stats = {"total_ota": len(ota_records), "total_pms": len(rezen_records),
             "match": 0, "diff": 0, "ota_only": 0, "pms_only": 0}

    # 向蜜鸟特殊：识别号匹配 + 储值卡兜底
    is_xiangminiao = channel_name == "向蜜鸟"

    for ota in ota_records:
        oid = _norm_orderno(ota.get(oid_col, ""))
        oamt = _norm_amount(ota.get(amt_col, 0))
        identify_no = _norm_orderno(ota.get("identify_no", "")) if is_xiangminiao else ""

        found = False
        ri = -1

        if oid:
            candidates = rezen_by_ext.get(oid, []) + rezen_by_order.get(oid, [])
            # 第一轮：优先找订单号匹配且金额一致的
            for ci in candidates:
                if ci in rezen_matched:
                    continue
                ramt = _norm_amount(rezen_records[ci].get("amount", 0))
                if abs(oamt - ramt) < 0.02:
                    ri = ci
                    found = True
                    break
            # 第二轮：只要订单号匹配就认定为同一订单（金额差异标记为diff）
            if not found:
                for ci in candidates:
                    if ci in rezen_matched:
                        continue
                    ri = ci
                    found = True
                    break

        # 向蜜鸟特殊策略B: 识别号(短码)匹配
        if not found and is_xiangminiao and identify_no:
            for ci in range(len(rezen_records)):
                if ci in rezen_matched:
                    continue
                rext = _norm_orderno(rezen_records[ci].get("ext_order", ""))
                rorder = _norm_orderno(rezen_records[ci].get("order", ""))
                # 识别号可能在外部订单号或订单号字段中
                if identify_no in rext or identify_no in rorder:
                    ramt = _norm_amount(rezen_records[ci].get("amount", 0))
                    if abs(oamt - ramt) < 0.02:
                        ri = ci
                        found = True
                        break

        # 向蜜鸟特殊策略C: 储值卡消费（OTA金额为0时直接匹配识别号）
        if not found and is_xiangminiao and oamt == 0 and identify_no:
            for ci in range(len(rezen_records)):
                if ci in rezen_matched:
                    continue
                rorder = _norm_orderno(rezen_records[ci].get("order", ""))
                rext = _norm_orderno(rezen_records[ci].get("ext_order", ""))
                if identify_no in rorder or identify_no in rext:
                    ri = ci
                    found = True
                    break

        if not found and not oid and not identify_no and oamt > 0:  # 必须没有订单号才允许金额兜底
            best_ci = -1
            best_diff = float("inf")
            for ci in range(len(rezen_records)):
                if ci in rezen_matched:
                    continue
                ramt = _norm_amount(rezen_records[ci].get("amount", 0))
                if ramt <= 0:
                    continue
                diff = abs(oamt - ramt)
                if diff < 5.0 and diff < best_diff:
                    best_diff = diff
                    best_ci = ci
            if best_ci >= 0:
                ri = best_ci
                found = True

        if found:
            rezen_matched.add(ri)
            ramt = _norm_amount(rezen_records[ri].get("amount", 0))
            diff = round(oamt - ramt, 2)
            if abs(diff) < 0.02:
                stats["match"] += 1
                status = "match"
            else:
                stats["diff"] += 1
                status = "diff"
            results.append({
                "status": status,
                "ota": ota,
                "pms": rezen_records[ri],
                "ota_amount": oamt,
                "pms_amount": ramt,
                "diff": diff,
                "ota_order": oid,
                "pms_ext_order": _norm_orderno(rezen_records[ri].get("ext_order", "")),
            })
        else:
            stats["ota_only"] += 1
            results.append({
                "status": "ota_only",
                "ota": ota,
                "pms": None,
                "ota_amount": oamt,
                "pms_amount": 0,
                "diff": oamt,
                "ota_order": oid,
                "pms_ext_order": "",
            })

    for i, r in enumerate(rezen_records):
        if i not in rezen_matched:
            stats["pms_only"] += 1
            results.append({
                "status": "pms_only",
                "ota": None,
                "pms": r,
                "ota_amount": 0,
                "pms_amount": _norm_amount(r.get("amount", 0)),
                "diff": _norm_amount(r.get("amount", 0)),
                "ota_order": "",
                "pms_ext_order": _norm_orderno(r.get("ext_order", "")),
            })

    return results, stats

def _match_ota_rezen_fnb(ota_records, rezen_records, channel_name):

    oci = OTA_CHANNEL_MAPPINGS.get(channel_name, {})
    price_col = oci.get("amount_col", "sell_price")

    # 统计 OTA 各金额出现次数，并收集券号
    ota_counts = {}
    ota_vouchers = {}
    ota_amount_total = 0.0
    for ota in ota_records:
        price = _norm_amount(ota.get(price_col, 0))
        if price == 0:
            continue
        ota_counts[price] = ota_counts.get(price, 0) + 1
        ota_vouchers.setdefault(price, []).append(str(ota.get("voucher_no", "") or ""))
        ota_amount_total += price

    # 统计 PMS 各金额出现次数，并收集结账单号
    pms_counts = {}
    pms_bills = {}
    pms_amount_total = 0.0
    for r in rezen_records:
        amt = _norm_amount(r.get("amount", 0))
        if amt == 0:
            continue
        pms_counts[amt] = pms_counts.get(amt, 0) + 1
        pms_bills.setdefault(amt, []).append(str(r.get("bill_no", "") or ""))
        pms_amount_total += amt

    results = []
    all_prices = set(ota_counts.keys()) | set(pms_counts.keys())
    stats = {
        "total_ota": len(ota_records),
        "total_pms": len(rezen_records),
        "match": 0,
        "diff": 0,
        "ota_only": 0,
        "pms_only": 0,
        "ota_amount_total": round(ota_amount_total, 2),
        "pms_amount_total": round(pms_amount_total, 2),
    }

    for price in sorted(all_prices):
        ota_cnt = ota_counts.get(price, 0)
        pms_cnt = pms_counts.get(price, 0)
        diff_cnt = ota_cnt - pms_cnt

        ota_amt_total = round(price * ota_cnt, 2)
        pms_amt_total = round(price * pms_cnt, 2)
        diff_amt = round(ota_amt_total - pms_amt_total, 2)

        if ota_cnt == pms_cnt and ota_cnt > 0:
            status = "match"
            stats["match"] += 1
        elif ota_cnt > 0 and pms_cnt == 0:
            status = "ota_only"
            stats["ota_only"] += 1
        elif pms_cnt > 0 and ota_cnt == 0:
            status = "pms_only"
            stats["pms_only"] += 1
        else:
            status = "diff"
            stats["diff"] += 1

        results.append({
            "status": status,
            "price": price,
            "ota_count": ota_cnt,
            "pms_count": pms_cnt,
            "diff_count": diff_cnt,
            "ota_amount_total": ota_amt_total,
            "pms_amount_total": pms_amt_total,
            "diff_amount": diff_amt,
            "ota_vouchers": ", ".join(v for v in ota_vouchers.get(price, []) if v),
            "pms_bills": ", ".join(b for b in pms_bills.get(price, []) if b),
        })

    return results, stats
