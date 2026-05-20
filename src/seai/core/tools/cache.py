"""
工具调用缓存模块
提供工具结果的缓存机制，减少重复调用
支持智能缓存键（感知文件修改时间等外部状态）
"""
import time
import hashlib
import json
import os
from typing import Any, Dict, Optional
from dataclasses import dataclass


@dataclass
class CacheEntry:
    """缓存条目"""
    value: Any
    timestamp: float
    ttl: float  # 生存时间（秒）


class ToolCache:
    """工具调用缓存"""

    def __init__(self, default_ttl: float = 300):  # 默认5分钟
        self._cache: Dict[str, CacheEntry] = {}
        self.default_ttl = default_ttl

    def _generate_key(self, tool_name: str, arguments: Dict) -> str:
        """生成智能缓存键（感知外部状态变化）"""
        if tool_name in ("read_file", "get_image_info", "encode_image", "encode_audio"):
            path = arguments.get("path", "")
            if path and os.path.exists(path):
                mtime = os.path.getmtime(path)
                key_data = f"{tool_name}:{path}:{mtime}"
                return hashlib.md5(key_data.encode()).hexdigest()

        if tool_name in ("web_search", "fetch_url"):
            query = arguments.get("query", "") or arguments.get("url", "")
            key_data = f"{tool_name}:{query}"
            return hashlib.md5(key_data.encode()).hexdigest()

        if tool_name == "grep":
            pattern = arguments.get("pattern", "")
            path = arguments.get("path", ".")
            mtime = os.path.getmtime(path) if os.path.exists(path) else 0
            key_data = f"{tool_name}:{pattern}:{path}:{mtime}"
            return hashlib.md5(key_data.encode()).hexdigest()

        if tool_name == "glob":
            pattern = arguments.get("pattern", "")
            path = arguments.get("path", ".")
            mtime = os.path.getmtime(path) if os.path.isdir(path) and os.path.exists(path) else 0
            key_data = f"{tool_name}:{pattern}:{path}:{mtime}"
            return hashlib.md5(key_data.encode()).hexdigest()

        # edit/bash/todo/write_file/delete_file — 不缓存可变操作
        if tool_name in ("edit", "bash", "todo", "write_file", "delete_file", "execute_command", "execute_python"):
            return None  # None 表示不可缓存

        args_str = json.dumps(arguments, sort_keys=True)
        key_data = f"{tool_name}:{args_str}"
        return hashlib.md5(key_data.encode()).hexdigest()

    def get(self, tool_name: str, arguments: Dict) -> Optional[Any]:
        """获取缓存值。返回 None 表示未命中或工具不可缓存。"""
        key = self._generate_key(tool_name, arguments)
        if key is None:
            return None

        if key not in self._cache:
            return None

        entry = self._cache[key]
        if time.time() - entry.timestamp > entry.ttl:
            del self._cache[key]
            return None

        return entry.value

    def set(self, tool_name: str, arguments: Dict, value: Any, ttl: Optional[float] = None):
        """设置缓存值。不可缓存的工具静默跳过。"""
        key = self._generate_key(tool_name, arguments)
        if key is None:
            return

        self._cache[key] = CacheEntry(
            value=value,
            timestamp=time.time(),
            ttl=ttl or self.default_ttl
        )

    def clear(self, tool_name: Optional[str] = None):
        """清除缓存"""
        if tool_name:
            keys_to_remove = [
                key for key in self._cache.keys()
                if key.startswith(hashlib.md5(tool_name.encode()).hexdigest()[:8])
            ]
            for key in keys_to_remove:
                del self._cache[key]
        else:
            self._cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        current_time = time.time()

        expired_count = 0
        for entry in self._cache.values():
            if current_time - entry.timestamp > entry.ttl:
                expired_count += 1

        return {
            "total_entries": len(self._cache),
            "expired_entries": expired_count,
            "memory_usage": sum(len(str(entry.value)) for entry in self._cache.values())
        }


tool_cache = ToolCache()