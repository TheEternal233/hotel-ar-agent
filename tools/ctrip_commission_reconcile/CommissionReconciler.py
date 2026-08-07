# -*- coding: utf-8 -*-
"""
CommissionReconciler
====================
接收携程 + PMS 解析结果，完成匹配、验算、输出差异。
"""
import logging
from collections import defaultdict
from typing import List, Dict, Any

logger = logging.getLogger(__name__)
class CommissionReconciler:
    def __init__(self, commission_rate=0.15, tolerance=0.05):
        self.rate = commission_rate
        self.tol = tolerance
        self.ctrip:List[Dict[str,Any]] = []
        self.pms:List[Dict[str,Any]]= []
        self.result:List[Dict[str,Any]] = []

    def load_ctrip(self, records:List[Dict[str,Any]])->None:
        self.ctrip = records

    def load_pms(self, records:List[Dict[str,Any]])->None:
        self.pms = records

    def match(self):
        """按 room_no#checkout 精确匹配"""
        pms_index = defaultdict(list)
        for idx,r in enumerate(self.pms):
            key = f"{r['room_no']}#{r['checkout']}"
            pms_index[key].append((idx, r))

        matched, unmatched_ctrip, unmatched_pms = [], [], []
        used_pms_idx = set()

        for c in self.ctrip:
            key = f"{c['room_no']}#{c['checkout']}"
            found=False

            for p_idx,p_rec in pms_index.get(key, []):
                if p_idx not in used_pms_idx:
                    matched.append({"key": key, "ctrip": c, "pms": p_rec})
                    used_pms_idx.add(p_idx)
                    found = True
                    break

            if not found:
                unmatched_ctrip.append(c)

        for idx,r in enumerate(self.pms):
            if idx not in used_pms_idx:
                unmatched_pms.append(r)


        logger.info(
            f"匹配完成: 匹配={len(matched)}, "
            f"携程未匹配={len(unmatched_ctrip)}, PMS未匹配={len(unmatched_pms)}"
        )

        return matched, unmatched_ctrip, unmatched_pms

    def verify(self, matched):
        rows = []
        for m in matched:
            c, p = m["ctrip"], m["pms"]
            room_price = p.get("room_price")

            if room_price is None:
                expected = None
                diff = None
                status = "NO_PMS_PRICE"
            else:
                expected=round(room_price*self.rate,2)
                diff=round(c["commission"]-expected,2)
                status = "OK" if abs(diff)<=self.tol else "DIFF"

            rows.append({
                "room_no": c["room_no"],
                "checkout": c["checkout"],
                "guest_name": c.get("guest_name") or p.get("guest_name"),
                "ctrip_comm": c["commission"],
                "pms_price": room_price,
                "expected": expected,
                "diff": diff,
                "status": status,
            })
        return rows

    def run(self)->List[Dict[str,Any]]:
        matched, u_ctrip, u_pms = self.match()
        verified = self.verify(matched)

        for c in u_ctrip:
            verified.append({
                "room_no": c["room_no"],
                "checkout": c["checkout"],
                "guest_name": c.get("guest_name"),
                "ctrip_comm": c["commission"],
                "pms_price": None,
                "expected": None,
                "diff": None,
                "status": "UNMATCHED",
            })

        for p in u_pms:
            verified.append({
                "room_no": p["room_no"],
                "checkout": p["checkout"],
                "guest_name": p.get("guest_name"),
                "ctrip_comm": None,
                "pms_price": p.get("room_price"),
                "expected": None,
                "diff": None,
                "status": "PMS_ONLY",
            })

        self.result = verified
        return self.result

    def summary(self)->Dict[str,int]:
        total = len(self.result)
        ok = sum(1 for r in self.result if r["status"] == "OK")
        diff = sum(1 for r in self.result if r["status"] == "DIFF")
        unmatched = sum(1 for r in self.result if r["status"] == "UNMATCHED")
        no_price = sum(1 for r in self.result if r["status"] == "NO_PMS_PRICE")
        pms_only = sum(1 for r in self.result if r["status"] == "PMS_ONLY")

        return {
            "total": total,
            "ok": ok,
            "diff": diff,
            "unmatched": unmatched,
            "no_pms_price": no_price,
            "pms_only": pms_only,
        }