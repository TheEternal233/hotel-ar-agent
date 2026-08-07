# -*- coding: utf-8 -*-
"""
CtripCommissionParser
=====================
负责解析携程佣金对账单的"服务费明细"，
提取：离店日、房号、服务费。
"""
import logging
from typing import List, Dict, Any

from tools.doc_parser import read_mapped

logger = logging.getLogger(__name__)

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

    def parse(self, path:str, sheet_name:str="服务费明细", header_row:int=2)->List[Dict[str,Any]]:
        """解析携程佣金明细"""

        try:
            raw = read_mapped(
                path=path,
                column_map=self.COLUMN_MAP,
                header_row=header_row,
                sheet_name=sheet_name,
            )
        except Exception as e:
            logger.error(f"读取携程文件失败:{e}")
            raise ValueError(f"无法解析携程文件，请检查 sheet 名称是否为 '{sheet_name}' 或表头是否在第 {header_row} 行")

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

        logger.info(f"携程解析完成:{len(records)}条记录")

        return records

    @staticmethod
    def _fmt_date(val)->str:
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
    def _fmt_num(val)->float:
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        try:
            return float(str(val).replace(",", "").replace("，",""))
        except (ValueError, TypeError):
            return 0.0


if __name__ == "__main__":
    parser = CtripCommissionParser()
    rows = parser.parse("/mnt/agents/upload/携程佣金.xls")
    print(f"共解析 {len(rows)} 条记录")
    for r in rows[:5]:
        print(r)




