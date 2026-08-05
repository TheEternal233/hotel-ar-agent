"""付款通知书 — 服务入口（API / Tool / CLI）"""

import os
import re
import logging
from datetime import datetime
from typing import Optional, Dict

from .doc_parser_pms import read_pms_receivable, _parse_date
from .config import DEFAULT_OUTPUT_DIR, NOTICE_TEMPLATE_PATH
from .utils import resolve_notice_month
from .builder import build_corp_summary, fill_notice_template

logger=logging.getLogger(__name__)
def generate_payment_notices(
    receivable_path: str,
    notice_month: str,
    output_dir: str = "",
    notice_date: Optional[str] = None,
    due_date: Optional[str] = None,
    open_balances: Optional[Dict[str, float]] = None,
    adjustment: Optional[float] = None,
    template_path: str = "",
) -> str:
    """生成付款通知书主入口"""
    if not os.path.exists(receivable_path):
        return f"错误：源文件不存在 {receivable_path}"

    tpl_path = template_path or NOTICE_TEMPLATE_PATH
    if not os.path.exists(tpl_path):
        return f"错误：模板文件不存在 {tpl_path}"

    out_dir = output_dir or DEFAULT_OUTPUT_DIR
    os.makedirs(out_dir, exist_ok=True)

    try:
        month_start, month_end, month_display = resolve_notice_month(notice_month)
    except ValueError as e:
        return f"错误：{e}"

    notice_dt = _parse_date(notice_date) or datetime.now()
    due_dt = _parse_date(due_date) if due_date else None

    raw_records = read_pms_receivable(receivable_path)
    if not raw_records:
        return "错误：PMS应收账务列表为空或读取失败"

    summary = build_corp_summary(raw_records, month_start, month_end, open_balances)
    if not summary:
        return f"未找到 {notice_month} 账期内的有效消费记录"

    generated_files = []
    failed_corps = []

    for corp_name, data in sorted(summary.items()):
        safe_name = re.sub(r'[\\/:*?"<>|]', "_", corp_name)
        filename = f"付款通知书_{safe_name}_{month_start.strftime('%Y%m')}.xlsx"
        output_path = os.path.join(out_dir, filename)

        try:
            fill_notice_template(
                corp_name=corp_name, data=data,
                template_path=tpl_path, output_path=output_path,
                notice_month_display=month_display,
                notice_date=notice_dt, due_date=due_dt, adjustment=adjustment,
            )
            generated_files.append({
                "corp": corp_name, "path": output_path,
                "details_count": len(data["details"]),
                "open_balance": data["open_balance"],
                "grand_total": data["grand_total"],
            })
        except Exception as e:
            failed_corps.append(f"{corp_name}: {e}")

    lines = [
        "付款通知书生成完成",
        f"账期: {notice_month} ({month_display})",
        f"通知书日期: {notice_dt.strftime('%Y-%m-%d')}",
        f"输出目录: {out_dir}",
        f"成功生成: {len(generated_files)} 份",
        "", "=" * 60, "生成文件清单:", "=" * 60,
    ]
    for item in generated_files:
        lines.extend([
            f"\n  客户: {item['corp']}",
            f"  文件: {os.path.basename(item['path'])}",
            f"  上期余额: {item['open_balance']:,.2f}",
            f"  本月明细: {item['details_count']} 笔",
            f"  应付总额: {item['grand_total']:,.2f}",
        ])
    if failed_corps:
        lines.extend(["\n", "=" * 60, f"失败 ({len(failed_corps)} 个):", "=" * 60])
        lines.extend(f"  {f}" for f in failed_corps)

    return "\n".join(lines)


# LangChain Tool
try:
    from langchain.tools import tool

    @tool
    def payment_notice_tool(
        receivable_path: str,
        notice_month: str,
        output_dir: str = "",
        notice_date: str = "",
        due_date: str = "",
    ) -> str:
        """PMS付款通知书生成，利用该工具可以生成对应的付款通知单"""
        return generate_payment_notices(
            receivable_path=receivable_path,
            notice_month=notice_month,
            output_dir=output_dir,
            notice_date=notice_date or None,
            due_date=due_date or None,
        )
except ImportError:
    payment_notice_tool = None


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("用法: python -m tools.protocol_settlement.notice_service <应收账务列表.xlsx> <账期(YYYY-MM)> [通知书日期(YYYY-MM-DD)]")
        sys.exit(1)
    print(generate_payment_notices(
        receivable_path=sys.argv[1],
        notice_month=sys.argv[2],
        notice_date=sys.argv[3] if len(sys.argv) > 3 else None,
    ))