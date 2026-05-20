"""
Tool Loop Engine 包 — 工具调用引擎

此包替代了原来的 core/tool_loop_engine.py 单文件，拆分为 3 个子模块：
- tool_selector: detect_intent, 工具分类常量, _auto_classify_tool, _build_tool_categories
- tool_formatter: build_text_tool_prompt, parse_text_tool_calls, normalize_messages
- engine: ToolLoopEngine (核心：run_tool_loop, process_stream, process_sync)
"""
from .tool_selector import (
    detect_intent,
    _auto_classify_tool,
    _build_tool_categories,
    TOOL_CATEGORY_RULES,
    TOOL_TO_MEM_TYPE,
    TOOL_STORAGE_MODE,
    INTENT_KEYWORDS,
)
from .tool_formatter import build_text_tool_prompt, parse_text_tool_calls, normalize_messages
from .engine import ToolLoopEngine
from .ooda_loop import OODAToolLoopEngine
