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

    for ota in ota_records:
        oid = _norm_orderno(ota.get(oid_col, ""))
        oamt = _norm_amount(ota.get(amt_col, 0))

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

        if not found and not oid and oamt > 0:
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


def match_xiangminiao(ota_list, pms_list, card_list=None):
    # pms建索引
    pms_by_ext = {}
    pms_by_order = {}
    for i, p in enumerate(pms_list):
        ext = _norm_orderno(p.get("ext_order", ""))
        od = _norm_orderno(p.get("order", ""))
        if ext:
            pms_by_ext.setdefault(ext, []).append(i)
        if od:
            pms_by_order.setdefault(od, []).append(i)

    # 储值卡建索引：按订单号挂储值卡实际扣款金额
    card_map = {}
    if card_list:
        for c in card_list:
            oid = _norm_orderno(c.get("order_id", ""))
            if oid:
                card_map[oid] = c

    used = set()
    out = []

    for ota in ota_list:
        oid = _norm_orderno(ota.get("order_id", ""))
        identify = _norm_orderno(ota.get("identify_no", ""))
        pay_type = str(ota.get("pay_type", ""))

        # 取OTA金额：储值卡优先读储值卡消费金额，否则读结算金额
        settle_amt= _norm_amount(ota.get("settle_amount", 0))

        if "储值" in pay_type or settle_amt == 0:
            amt = _norm_amount(ota.get("card_pay_amount", 0))
            if amt == 0 and oid in card_map:
                amt = _norm_amount(card_map[oid].get("card_amount", 0))
            if amt == 0:
                amt = settle_amt
            if amt == 0:
                amt= _norm_amount(ota.get("actual_amount", 0))
        else:
            amt = settle_amt
            if amt == 0:
                amt = _norm_amount(ota.get("actual_settle", 0))

        found = False
        idx = -1


        if oid:
            cands = pms_by_ext.get(oid, []) + pms_by_order.get(oid, [])
            for i in cands:
                if i in used:
                    continue
                if abs(amt - _norm_amount(pms_list[i].get("amount", 0))) < 0.02:
                    idx = i
                    found = True
                    break
            if not found and cands:
                for i in cands:
                    if i in used:
                        continue
                    idx = i
                    found = True
                    break


        if not found and identify:
            for i in range(len(pms_list)):
                if i in used:
                    continue
                ext = _norm_orderno(pms_list[i].get("ext_order", ""))
                od = _norm_orderno(pms_list[i].get("order", ""))
                if identify in ext or identify in od:
                    if abs(amt - _norm_amount(pms_list[i].get("amount", 0))) < 0.02:
                        idx = i
                        found = True
                        break

            if not found:
                for i in range(len(pms_list)):
                    if i in used:
                        continue
                    ext = _norm_orderno(pms_list[i].get("ext_order", ""))
                    od = _norm_orderno(pms_list[i].get("order", ""))
                    if identify in ext or identify in od:
                        idx = i
                        found = True
                        break


        if not found and amt > 0 and not oid and not identify:
            best_i = -1
            best_d = 999999
            for i in range(len(pms_list)):
                if i in used:
                    continue
                pms_amt = _norm_amount(pms_list[i].get("amount", 0))
                if pms_amt <= 0:
                    continue
                d = abs(amt - pms_amt)
                if d < 5 and d < best_d:
                    best_d = d
                    best_i = i
            if best_i >= 0:
                idx = best_i
                found = True


        if found:
            used.add(idx)
            pms_amt = _norm_amount(pms_list[idx].get("amount", 0))
            diff = round(amt - pms_amt, 2)
            is_card_full=("储值" in pay_type and pms_amt ==0 and amt > 0)
            out.append({
                "status": "match" if (abs(diff) < 0.02 or is_card_full) else "diff",
                "ota": ota,
                "pms": pms_list[idx],
                "ota_amount": amt,
                "pms_amount": pms_amt,
                "diff": diff,
                "ota_order": oid,
                "pms_ext_order": _norm_orderno(pms_list[idx].get("ext_order", "")),
            })
        else:
            out.append({
                "status": "ota_only",
                "ota": ota,
                "pms": None,
                "ota_amount": amt,
                "pms_amount": 0,
                "diff": amt,
                "ota_order": oid,
                "pms_ext_order": "",
            })


    for i, p in enumerate(pms_list):
        if i not in used:
            out.append({
                "status": "pms_only",
                "ota": None,
                "pms": p,
                "ota_amount": 0,
                "pms_amount": _norm_amount(p.get("amount", 0)),
                "diff": _norm_amount(p.get("amount", 0)),
                "ota_order": "",
                "pms_ext_order": _norm_orderno(p.get("ext_order", "")),
            })

    stats = {
        "total_ota": len(ota_list),
        "total_pms": len(pms_list),
        "match": sum(1 for r in out if r["status"] == "match"),
        "diff": sum(1 for r in out if r["status"] == "diff"),
        "ota_only": sum(1 for r in out if r["status"] == "ota_only"),
        "pms_only": sum(1 for r in out if r["status"] == "pms_only"),
    }
    return out, stats