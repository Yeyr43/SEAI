"""
SEAI 联网搜索模块（infra 层 — 从 core.net 重导出）
"""
from ..net import (
    enable, disable, is_enabled, set_enabled, web_search,
    clear_cache, get_backend_stats,
)
