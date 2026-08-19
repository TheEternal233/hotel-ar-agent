"""
工具容错包装器 —— 为 LangChain Tool 注入重试/超时/失败隔离能力

不修改原始工具函数，通过包装生成新的 StructuredTool，
保留原始 name / description / args_schema，对 LLM 完全透明。

使用方式（在 agent.py 中）：
    from orchestrator.tool_wrapper import with_resilience
    TOOLS = [
        with_resilience(ar_recon, retries=2, timeout=120),
        with_resilience(bocha_search, retries=2, timeout=30),
        ...
    ]
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime

from langchain_core.tools import StructuredTool

from enums.paths import BASE_DIR

logger = logging.getLogger(__name__)


def _record_tool_failure(tool_name: str, error: str):
    try:
        failed_log = os.path.join(BASE_DIR, "data", "failed_tasks.jsonl")
        os.makedirs(os.path.dirname(failed_log), exist_ok=True)
        with open(failed_log, "a", encoding="utf-8") as f:
            f.write(json.dumps({
                "timestamp": datetime.now().isoformat(),
                "tool": tool_name,
                "error": error,
                "status": "pending_review",
                "source": "ai_conversation",
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass


def with_resilience(tool, retries: int = 2, timeout: int | None = None):
    """为 LangChain Tool 添加重试、超时、失败隔离能力。

    Args:
        tool:    原始 LangChain StructuredTool（@tool 装饰的函数）
        retries: 最大重试次数（不含首次调用），默认 2
        timeout: 单次调用超时秒数，None 表示不超时

    Returns:
        包装后的 StructuredTool，具备异常兜底能力。
        重试全部失败时，返回友好错误消息而非抛出异常，
        同时将失败记录到 data/failed_tasks.jsonl 供人工处理。
    """
    tool_name = tool.name

    async def _resilient_coroutine(**kwargs):
        last_error = None
        for attempt in range(retries + 1):
            try:
                if timeout:
                    result = await asyncio.wait_for(
                        tool.ainvoke(kwargs),
                        timeout=timeout,
                    )
                else:
                    result = await tool.ainvoke(kwargs)
                return result
            except asyncio.TimeoutError:
                last_error = f"执行超时（>{timeout}秒）"
                logger.warning(
                    f"[工具容错] {tool_name} 第{attempt + 1}次超时（>{timeout}s）"
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"[工具容错] {tool_name} 第{attempt + 1}次失败: {e}"
                )
            if attempt < retries:
                await asyncio.sleep(1 * (attempt + 1))

        _record_tool_failure(tool_name, str(last_error))
        return (
            f"[工具失败] {tool_name} 已重试{retries}次仍失败: {str(last_error)}。"
            f" 系统已记录此问题，请人工介入处理。"
        )

    def _resilient_func(**kwargs):
        last_error = None
        for attempt in range(retries + 1):
            try:
                result = tool.invoke(kwargs)
                return result
            except Exception as e:
                last_error = e
                logger.warning(
                    f"[工具容错] {tool_name} 第{attempt + 1}次失败: {e}"
                )
                if attempt < retries:
                    time.sleep(1 * (attempt + 1))

        _record_tool_failure(tool_name, str(last_error))
        return (
            f"[工具失败] {tool_name} 已重试{retries}次仍失败: {str(last_error)}。"
            f" 系统已记录此问题，请人工介入处理。"
        )

    if tool.coroutine:
        return StructuredTool(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            coroutine=_resilient_coroutine,
        )
    else:
        return StructuredTool(
            name=tool.name,
            description=tool.description,
            args_schema=tool.args_schema,
            func=_resilient_func,
        )