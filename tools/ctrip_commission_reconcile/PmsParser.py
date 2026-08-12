# -*- coding: utf-8 -*-
"""
PmsParser
=========
解析酒店 PMS 退房/结账明细，
提取：房号、离店日、房价、客人姓名。
"""
import logging
import re
from typing import List, Dict, Any
from datetime import datetime,timedelta
from tools.doc_parser import read_mapped
from utils.common_func import _clean_val

logger=logging.getLogger(__name__)
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

    def parse(self, path:str, sheet_name:str=None, header_row:int=1)->List[Dict[str,Any]]:
        """解析PMS明细"""
        try:
            raw = read_mapped(
                path=path,
                column_map=self.COLUMN_MAP,
                header_row=header_row,
                sheet_name=sheet_name,
            )
        except Exception as e:
            logger.error(f"读取PMS文件失败:{e}")
            raise ValueError(f"无法解析 PMS 文件，请检查列名是否包含房号/离店日期/房价等字段")

        records = []
        for rec in raw:
            room_no=_clean_val(rec.get("room_no"))
            guest_name=_clean_val(rec.get("guest_name"))
            checkout_row=_clean_val(rec.get("checkout"))
            room_price_row=_clean_val(rec.get("room_price"))
            order_id=_clean_val(rec.get("order_id"))
            # 跳过空行
            if not room_no and not guest_name:
                continue

            checkout = self._fmt_date(checkout_row)
            room_price = self._fmt_num(room_price_row,default=None)

            # 处理多房号（部分 PMS 会写成 "801,802"）
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
                    "room_price": room_price,
                    "guest_name": guest_name,
                    "order_id":   order_id,
                })
        logger.info(f"PMS解析完成:{len(records)}条记录")
        return records

    @staticmethod
    def _fmt_date(val):
        if val is None or val == "":
            return None

        try:
            if hasattr(val, "strftime"):
                return val.strftime("%Y-%m-%d")
        except (ValueError,AttributeError):
            return None

        # Excel序列号
        if isinstance(val, (int,float)) and not isinstance(val,bool):
            if 1<=val<=50000:
                try:
                    d=datetime(1899,12,31)+timedelta(days=int(val))
                    return d.strftime("%Y-%m-%d")
                except Exception:
                    pass

        #字符串解析
        if isinstance(val,str):
            s=val.strip()
            if not s:
                return None
            # 中文日期：2024年1月5日、2024年01月05日
            m = re.match(r"(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})[日]?", s)
            if m:
                try:
                    y,mth,d=map(int,m.groups())
                    return datetime(y,mth,d).strftime("%Y-%m-%d")
                except ValueError:
                    pass

            # 标准格式
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
    def _fmt_num(val,default=0.0):
        if val is None:
            return default
        if isinstance(val, bool):
            return default
        if isinstance(val, (int, float)):
            return float(val)
        try:
            return float(str(val).replace(",", "").replace("，", ""))
        except (ValueError, TypeError):
            return default

