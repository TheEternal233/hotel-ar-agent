# -*- coding: utf-8 -*-
"""
PmsParser
=========
解析酒店 PMS 退房/结账明细，
提取：房号、离店日、房价、客人姓名。
"""
from tools.doc_parser import read_mapped


class PmsParser:
    """PMS 账单解析器"""

    # 支持多种常见列名变体，自动匹配
    COLUMN_MAP = {
        "room_no":    ["房号", "房间号", "Room", "room_no", "Rm"],
        "checkout":   ["离店日期", "退房日期", "离店日", "Check-out", "Departure", "退房时间"],
        "room_price": ["房价", "房费", "实收房价", "Room Charge", "房费合计", "总房费"],
        "guest_name": ["客人姓名", "入住人", "姓名", "Guest Name", "住客"],
        "order_id":   ["订单号", "外部订单号", "携程订单号", "Order No", "Ext Order"],
    }

    def parse(self, path, sheet_name=None, header_row=1):
        raw = read_mapped(
            path=path,
            column_map=self.COLUMN_MAP,
            header_row=header_row,
            sheet_name=sheet_name,
        )

        records = []
        for rec in raw:
            # 跳过空行
            if not rec.get("room_no") and not rec.get("guest_name"):
                continue

            checkout = self._fmt_date(rec.get("checkout"))
            room_price = self._fmt_num(rec.get("room_price"))

            # 处理多房号（部分 PMS 会写成 "801,802"）
            room_raw = str(rec.get("room_no") or "")
            for rid in room_raw.split(","):
                rid = rid.strip()
                if not rid:
                    continue
                records.append({
                    "room_no":    rid,
                    "checkout":   checkout,
                    "room_price": room_price,
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
            for fmt in ["%Y/%m/%d", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"]:
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
            return float(str(val).replace(",", "").replace("，", ""))
        except (ValueError, TypeError):
            return 0.0


if __name__ == "__main__":
    parser = PmsParser()
    rows = parser.parse("pms_demo.xlsx")
    print(f"共解析 {len(rows)} 条记录")
    for r in rows[:5]:
        print(r)