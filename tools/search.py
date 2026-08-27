import os
import json
from dotenv import load_dotenv
from langchain.tools import tool

load_dotenv()

# 模块级全局 AsyncClient，支持连接复用和 HTTP/2
_httpx_client = None


def _get_httpx_client():
    """获取全局 AsyncClient 实例（延迟初始化，连接复用）。"""
    global _httpx_client
    if _httpx_client is None:
        import httpx
        _httpx_client = httpx.AsyncClient(
            timeout=30,
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
        )
    return _httpx_client


@tool
async def bocha_search(query: str) -> str:
    """使用 Bocha 搜索 API 进行网络检索，返回搜索结果摘要和详细列表。
    适用于需要实时信息、新闻、事实查询或任何网络公开资料的场景。"""
    API_KEY = os.environ.get("BOCHA_API_KEY")
    if not API_KEY:
        return "错误：请在 .env 中设置 BOCHA_API_KEY"

    url = "https://api.bocha.cn/v1/web-search"
    payload = {
        "query": query,
        "summary": True,
        "freshness": "noLimit",
        "count": 10
    }
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json"
    }

    try:
        client = _get_httpx_client()
        response = await client.post(url, headers=headers, json=payload)
        data = response.json()

        if response.status_code != 200:
            return f"搜索失败：{json.dumps(data, ensure_ascii=False)}"

        web_pages = data.get("data", {}).get("webPages", {}).get("value", [])
        summary = data.get("data", {}).get("summary", "")

        output = f"📝 搜索摘要：{summary}\n\n📌 搜索结果：\n"
        for idx, item in enumerate(web_pages, 1):
            title = item.get("name", "无标题")
            snippet = item.get("snippet", "无摘要")
            source = item.get("siteName", "未知来源")
            url_link = item.get("url", "")
            output += f"{idx}. **{title}**\n   {snippet}\n   来源：{source} | 链接：{url_link}\n\n"

        return output.strip() if output else "未找到相关结果。"

    except Exception as e:
        return f"⚠️ 搜索异常：{str(e)}"