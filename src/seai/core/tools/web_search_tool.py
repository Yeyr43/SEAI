"""
web_search_tool — 联网搜索工具 (Rust SearchClient 加速)

两层回退: Rust SearchClient.search → Python 多后端 net.py
"""
from typing import Dict, Any


async def execute(args: Dict[str, Any]) -> str:
    query = args.get("query", "").strip()
    max_results = int(args.get("max_results", 5))
    backend = args.get("backend", None)

    if not query:
        return "错误: 未提供搜索关键词 (query)"

    # L1: Rust SearchClient
    try:
        from .._rust import is_rust_available, get_search_client
        if is_rust_available():
            client = get_search_client()
            if not client.is_enabled():
                return "联网搜索功能未启用。如需使用，请在对话中开启 web_search 选项。"
            result = client.search(query, max_results, backend)
            if result and not result.startswith("[search]"):
                return result
    except Exception:
        pass

    # L2: Python 多后端 net.py
    from ..net import web_search as py_search, is_enabled as py_enabled
    if not py_enabled():
        return "联网搜索功能未启用。如需使用，请在对话中开启 web_search 选项。"
    return py_search(query, max_results, backend)


def get_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "执行联网搜索，支持多后端自动回退（Brave → Serper → DuckDuckGo）。结果缓存 300 秒。需要 BRAVE_API_KEY 或 SERPER_API_KEY 环境变量来使用付费后端，否则自动回退到 DuckDuckGo。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "max_results": {"type": "integer", "description": "最大返回结果数，默认 5", "default": 5},
                    "backend": {"type": "string", "description": "指定搜索后端: brave, serper, ddg。不指定则自动回退。", "enum": ["brave", "serper", "ddg"]},
                },
                "required": ["query"]
            }
        }
    }
