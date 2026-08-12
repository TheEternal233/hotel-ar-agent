# -*- coding: utf-8 -*-
"""
CtripCommissionParser
=====================
负责解析携程佣金对账单的"服务费明细"，
提取：离店日、房号、服务费。
"""
import logging
from typing import List, Dict, Any
import re
from datetime import datetime,timedelta
from tools.doc_parser import read_mapped
from utils.common_func import _clean_val

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
            room_no = _clean_val(rec.get("room_no"))
            guest_name = _clean_val(rec.get("guest_name"))
            checkout_row = _clean_val(rec.get("checkout"))
            order_id = _clean_val(rec.get("order_id"))
            commission_row=_clean_val(rec.get("commission"))
            nights = _clean_val(rec.get("nights"))
            if order_id is None or str(order_id).strip() == "":
                continue

            checkout = self._fmt_date(checkout_row)
            commission = self._fmt_num(commission_row)
            nights = self._fmt_num(nights)

            # 处理多房号（如 "110691,110692" 拆成多条）
            room_raw = str(room_no or "")
            # 处理Excel数字格式带来的.0后缀
            if "." in room_raw:
                room_raw=room_raw.rstrip("0").rstrip(".")
            for rid in room_raw.split(","):
                rid = rid.strip()
                if not rid:
                    continue
                records.append({
                    "room_no":    rid,
                    "checkout":   checkout,
                    "commission": commission,
                    "nights":     nights,
                    "guest_name": guest_name,
                    "order_id":   order_id,
                })

        logger.info(f"携程解析完成:{len(records)}条记录")

        return records

    @staticmethod
    def _fmt_date(val)->str:
        if val is None or val == "":
            return None

        try:
            if hasattr(val, "strftime"):
                return val.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            return None

        if isinstance(val, (int, float)) and not isinstance(val, bool):
            if 1 <= val <= 50000:
                try:
                    d = datetime(1899, 12, 31) + timedelta(days=int(val))
                    return d.strftime("%Y-%m-%d")
                except Exception:
                    pass

        if isinstance(val, str):
            s = val.strip()
            if not s:
                return None

            m = re.match(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})[日]?", s)
            if m:
                try:
                    y, mth, d = map(int, m.groups())
                    return datetime(y, mth, d).strftime("%Y-%m-%d")
                except ValueError:
                    pass

            for fmt in [
                "%Y/%m/%d", "%Y-%m-%d", "%Y%m%d",
                "%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%d/%m/%Y", "%m/%d/%Y",
            ]:
                try:
                    return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
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
