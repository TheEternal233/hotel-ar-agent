# -*- coding: utf-8 -*-
"""
CtripCommissionParser
=====================
负责解析携程佣金对账单的"服务费明细"，
提取：离店日、房号、服务费。
"""
from tools.doc_parser import read_mapped


class CtripCommissionParser:
    """携程佣金账单解析器"""

    COLUMN_MAP = {
        "order_id":   ["订单号"],
        "room_no":    ["房号"],
        "checkout":   ["离店日"],
        "guest_name": ["客人姓名"],
        "nights":     ["间夜"],
        "commission": ["服务费"],
    }

    def parse(self, path, sheet_name="服务费明细", header_row=2):
        raw = read_mapped(
            path=path,
            column_map=self.COLUMN_MAP,
            header_row=header_row,
            sheet_name=sheet_name,
        )

        records = []
        for rec in raw:
            if not rec.get("order_id"):
                continue

            checkout = self._fmt_date(rec.get("checkout"))
            commission = self._fmt_num(rec.get("commission"))
            nights = self._fmt_num(rec.get("nights"))

            # 处理多房号（如 "110691,110692" 拆成多条）
            room_raw = str(rec.get("room_no") or "")
            for rid in room_raw.split(","):
                rid = rid.strip()
                if not rid:
                    continue
                records.append({
                    "room_no":    rid,
                    "checkout":   checkout,
                    "commission": commission,
                    "nights":     nights,
                    "guest_name": rec.get("guest_name"),
                    "order_id":   rec.get("order_id"),
                })

        return records

    @staticmethod
    def _fmt_date(val):
        if hasattr(val, "strftime"):
            return val.strftime("%Y-%m-%d")
        if isinstance(val, str) and val.strip():
            from datetime import datetime
            for fmt in ["%Y/%m/%d", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(val.strip(), fmt).strftime("%Y-%m-%d")
                except ValueError:
                    pass
        return val

    @staticmethod
    def _fmt_num(val):
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        try:
            return float(str(val).replace(",", ""))
        except (ValueError, TypeError):
            return 0.0


if __name__ == "__main__":
    parser = CtripCommissionParser()
    rows = parser.parse("/mnt/agents/upload/携程佣金.xls")
    print(f"共解析 {len(rows)} 条记录")
    for r in rows[:5]:
        print(r)