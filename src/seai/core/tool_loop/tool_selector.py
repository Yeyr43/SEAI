"""工具选择与意图检测 — 工具分类、意图关键词、自动归类"""
from typing import List, Dict

TOOL_CATEGORY_RULES = {
    "file": ("read", "write", "delete", "list", "file", "dir", "path", "copy", "move", "rename"),
    "search": ("search", "fetch", "web", "url", "http", "get"),
    "code": ("calc", "python", "script", "exec", "eval", "compile", "fix_", "code"),
    "management": ("schedule", "todo", "task", "plan", "remind", "notify"),
    "media": ("image", "audio", "video", "encode", "decode"),
}

TOOL_TO_MEM_TYPE = {
    "read_file": lambda args: "code" if args.get("path", "").endswith((".py", ".js", ".ts", ".java", ".go", ".rs")) else ("file_snapshot" if args.get("path", "").endswith((".md", ".txt", ".log", ".json", ".yaml", ".yml")) else "text"),
    "write_file": lambda args: "code" if args.get("path", "").endswith((".py", ".js", ".ts", ".java", ".go", ".rs")) else "file_snapshot",
    "fetch_url": lambda _: "url",
    "web_search": lambda _: "search_result",
    "encode_image": lambda _: "image_analysis",
    "encode_audio": lambda _: "audio_analysis",
}

TOOL_STORAGE_MODE = {
    "read_file": "original",
    "write_file": "original",
    "encode_image": "original",
    "encode_audio": "original",
    "fetch_url": "summary",
    "web_search": "summary",
}

INTENT_KEYWORDS = {
    "coding": ["代码", "bug", "函数", "编程", "code", "function", "debug", "python", "java", "写一个", "实现", "报错", "错误"],
    "search": ["搜索", "搜寻", "查一下", "查", "搜", "网页", "链接", "上网", "新闻", "search", "find", "lookup", "最新"],
    "creative": ["写", "画", "创作", "诗", "故事", "write", "create", "draw"],
    "time": ["明天", "今天", "下周", "周", "待办", "提醒", "日程", "安排", "几点"],
}


def _auto_classify_tool(tool_name: str, tool_desc: str = "") -> str:
    """根据工具名和描述自动归类"""
    combined = (tool_name + " " + tool_desc).lower()
    for category, keywords in TOOL_CATEGORY_RULES.items():
        if any(kw in combined for kw in keywords):
            return category
    return "general"


def _build_tool_categories(tool_definitions: list) -> dict:
    """从工具定义动态构建类别映射"""
    categories = {}
    for td in tool_definitions:
        func = td.get("function", td)
        name = func.get("name", "")
        desc = func.get("description", "")
        cat = _auto_classify_tool(name, desc)
        categories.setdefault(cat, []).append(name)
    return categories


def detect_intent(query: str) -> str:
    """检测用户意图（供 tool_loop 和 reflection_engine 共用）"""
    query_lower = query.lower()
    for intent, keywords in INTENT_KEYWORDS.items():
        if any(kw in query_lower for kw in keywords):
            return intent
    return "general"
