"""night_audit API 层：FastAPI 端点适配"""

from typing import List

from fastapi import HTTPException

from .aggregator import aggregate_daily_check, auto_aggregate_daily_check


def daily_check_handler(ota_paths: List[str], card_paths: List[str]) -> str:
    """处理每日核对请求，返回汇总结果文本"""
    try:
        output_path = aggregate_daily_check(ota_paths, card_paths)

        lines = [
            "=" * 60,
            "           每日夜审汇总报告",
            "=" * 60,
            "",
            f"汇总文件: {output_path}",
            "",
            f"OTA 对账结果文件数: {len(ota_paths)}",
        ]
        for p in ota_paths:
            lines.append(f"  - {p}")

        lines.append("")
        lines.append(f"信用卡对账结果文件数: {len(card_paths)}")
        for p in card_paths:
            lines.append(f"  - {p}")

        lines.extend([
            "",
            "=" * 60,
            "汇总完成，请下载汇总文件查看详细数据。",
            "=" * 60,
        ])

        return "\n".join(lines)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"汇总失败: {e}")


def auto_daily_check_handler() -> str:
    """自动扫描 output 目录下的对账结果并汇总"""
    try:
        output_path = auto_aggregate_daily_check()

        lines = [
            "=" * 60,
            "           每日夜审汇总报告（自动模式）",
            "=" * 60,
            "",
            f"汇总文件: {output_path}",
            "",
            "数据来源:",
            "  - OTA对账结果: output/OTA对账/",
            "  - 信用卡对账结果: output/信用卡审核/",
            "",
            "=" * 60,
            "汇总完成，请下载汇总文件查看详细数据。",
            "=" * 60,
        ]

        return "\n".join(lines)

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"汇总失败: {e}")