"""
SEAI 联网搜索模块（tools 层 — 从 core.net 重导出）
供 registry.py 的 `from .net import web_search` 使用
"""
from ..net import (
    enable, disable, is_enabled, set_enabled, web_search,
    clear_cache, get_backend_stats,
)
