from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
import os
import threading

load_dotenv()

# 模块级单例缓存，避免每次调用重复创建 LLM 实例
_llm_instance: ChatOpenAI | None = None
_llm_lock = threading.Lock()


def get_llm() -> ChatOpenAI:
    """获取 LLM 实例（单例模式，线程安全）。

    首次调用时创建 ChatOpenAI 实例并缓存，后续调用直接返回缓存实例，
    避免重复初始化带来的连接开销和内存分配。
    """
    global _llm_instance
    if _llm_instance is not None:
        return _llm_instance

    with _llm_lock:
        # 双重检查，避免多个线程同时创建
        if _llm_instance is not None:
            return _llm_instance

        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("please input api_key")

        _llm_instance = ChatOpenAI(
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com/v1",
            api_key=api_key,
            temperature=0,
        )
        return _llm_instance