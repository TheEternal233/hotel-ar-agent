# -*- coding: utf-8 -*-
"""
CommissionReconciler
====================
接收携程 + PMS 解析结果，完成匹配、验算、输出差异。
"""

class CommissionReconciler:
    def __init__(self, commission_rate=0.15, tolerance=0.05):
        self.rate = commission_rate
        self.tol = tolerance
        self.ctrip = []
        self.pms = []
        self.result = []

    def load_ctrip(self, records):
        self.ctrip = records

    def load_pms(self, records):
        self.pms = records

    def match(self):
        """按 room_no#checkout 精确匹配"""
        pms_index = {}
        for r in self.pms:
            key = f"{r['room_no']}#{r['checkout']}"
            pms_index[key] = r

        matched, unmatched_ctrip, unmatched_pms = [], [], []
        used_keys = set()

        for c in self.ctrip:
            key = f"{c['room_no']}#{c['checkout']}"
            p = pms_index.get(key)

            if p:
                matched.append({"key": key, "ctrip": c, "pms": p})
                used_keys.add(key)
            else:
                unmatched_ctrip.append(c)

        for r in self.pms:
            key = f"{r['room_no']}#{r['checkout']}"
            if key not in used_keys:
                unmatched_pms.append(r)

        return matched, unmatched_ctrip, unmatched_pms

    def verify(self, matched):
        rows = []
        for m in matched:
            c, p = m["ctrip"], m["pms"]
            expected = round(p["room_price"] * self.rate, 2) if p.get("room_price") else None
            diff = round(c["commission"] - expected, 2) if expected is not None else None

            status = "OK"
            if diff is not None and abs(diff) > self.tol:
                status = "DIFF"
            elif diff is None:
                status = "NO_PMS_PRICE"

            rows.append({
                "room_no": c["room_no"],
                "checkout": c["checkout"],
                "guest_name": c.get("guest_name"),
                "ctrip_comm": c["commission"],
                "pms_price": p.get("room_price"),
                "expected": expected,
                "diff": diff,
                "status": status,
            })
        return rows

    def run(self):
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

        self.result = verified
        return self.result

    def summary(self):
        total = len(self.result)
        ok = sum(1 for r in self.result if r["status"] == "OK")
        diff = sum(1 for r in self.result if r["status"] == "DIFF")
        unmatched = sum(1 for r in self.result if r["status"] in ("UNMATCHED", "NO_PMS_PRICE"))
        print(f"总记录:{total} | 正常:{ok} | 差异:{diff} | 未匹配:{unmatched}")