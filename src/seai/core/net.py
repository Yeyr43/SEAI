"""
SEAI 联网搜索模块 — 多后端搜索 + 缓存 + 限流 + 熔断

后端优先级: Brave Search API → Serper.dev → DuckDuckGo (DDGS)
每后端独立熔断器，LRU 缓存 (200 条, 300s TTL)，令牌桶限流
"""
import os
import time
import threading
from typing import Dict, List, Optional, Tuple

from loguru import logger

_enabled = True

# ══════════════════════════════════════════════════
# 后端 API Key（环境变量）
# ══════════════════════════════════════════════════
BRAVE_API_KEY = os.environ.get("BRAVE_API_KEY", "")
SERPER_API_KEY = os.environ.get("SERPER_API_KEY", "")


def enable():
    global _enabled
    _enabled = True


def disable():
    global _enabled
    _enabled = False


def is_enabled() -> bool:
    return _enabled


def set_enabled(val: bool):
    global _enabled
    _enabled = bool(val)


# ══════════════════════════════════════════════════
# LRU 缓存
# ══════════════════════════════════════════════════

class _SearchCache:
    """线程安全的 LRU 缓存（基于字典插入顺序）"""

    def __init__(self, max_size: int = 200, ttl_seconds: float = 300.0):
        self._max_size = max_size
        self._ttl = ttl_seconds
        self._store: Dict[str, Tuple[float, str]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, value = entry
            if time.time() - ts > self._ttl:
                del self._store[key]
                return None
            # 移到末尾（LRU: 最近访问）
            del self._store[key]
            self._store[key] = (ts, value)
            return value

    def set(self, key: str, value: str):
        with self._lock:
            if key in self._store:
                del self._store[key]
            elif len(self._store) >= self._max_size:
                # 删除最旧条目（字典第一项）
                oldest = next(iter(self._store))
                del self._store[oldest]
            self._store[key] = (time.time(), value)

    def clear(self):
        with self._lock:
            self._store.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._store)


_search_cache = _SearchCache()


# ══════════════════════════════════════════════════
# 令牌桶限流器
# ══════════════════════════════════════════════════

class _TokenBucket:
    """令牌桶限流器"""

    def __init__(self, rate: float = 10.0, burst: int = 20):
        self._rate = rate  # 每秒生成令牌数
        self._burst = burst
        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self) -> bool:
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
            self._last_refill = now
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False


# 每后端独立限流器
_rate_limiters: Dict[str, _TokenBucket] = {
    "brave": _TokenBucket(rate=10.0, burst=20),
    "serper": _TokenBucket(rate=10.0, burst=20),
    "ddg": _TokenBucket(rate=5.0, burst=10),
}

# 后端统计
_backend_stats: Dict[str, Dict[str, int]] = {
    "brave": {"success": 0, "failure": 0},
    "serper": {"success": 0, "failure": 0},
    "ddg": {"success": 0, "failure": 0},
}


def get_backend_stats() -> dict:
    return {
        "cache_size": len(_search_cache),
        "backends": dict(_backend_stats),
    }


def clear_cache():
    _search_cache.clear()


# ══════════════════════════════════════════════════
# 各后端搜索实现
# ══════════════════════════════════════════════════

def _search_brave(query: str, max_results: int) -> Tuple[Optional[str], Optional[str]]:
    """Brave Search API: https://api.search.brave.com/res/v1/web/search"""
    if not BRAVE_API_KEY:
        return None, "BRAVE_API_KEY 未设置"

    if not _rate_limiters["brave"].acquire():
        return None, "Brave Search 限流，请稍后重试"

    try:
        import urllib.request
        import json as _json

        url = f"https://api.search.brave.com/res/v1/web/search?q={urllib.request.quote(query)}&count={max_results}"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "X-Subscription-Token": BRAVE_API_KEY,
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())

        results = []
        for r in data.get("web", {}).get("results", [])[:max_results]:
            results.append(f"{len(results)+1}. {r.get('title', '')}\n   {r.get('url', '')}\n   {r.get('description', '')}")

        if not results:
            return None, "Brave Search 未找到结果"

        _backend_stats["brave"]["success"] += 1
        return "\n\n".join(results), None

    except Exception as e:
        _backend_stats["brave"]["failure"] += 1
        return None, f"Brave Search 失败: {e}"


def _search_serper(query: str, max_results: int) -> Tuple[Optional[str], Optional[str]]:
    """Serper.dev Google Search API: https://google.serper.dev/search"""
    if not SERPER_API_KEY:
        return None, "SERPER_API_KEY 未设置"

    if not _rate_limiters["serper"].acquire():
        return None, "Serper 限流，请稍后重试"

    try:
        import urllib.request
        import json as _json

        url = "https://google.serper.dev/search"
        payload = _json.dumps({"q": query, "num": max_results}).encode()
        req = urllib.request.Request(url, data=payload, headers={
            "X-API-KEY": SERPER_API_KEY,
            "Content-Type": "application/json",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode())

        results = []
        for r in data.get("organic", [])[:max_results]:
            results.append(f"{len(results)+1}. {r.get('title', '')}\n   {r.get('link', '')}\n   {r.get('snippet', '')}")

        if not results:
            return None, "Serper 未找到结果"

        _backend_stats["serper"]["success"] += 1
        return "\n\n".join(results), None

    except Exception as e:
        _backend_stats["serper"]["failure"] += 1
        return None, f"Serper 失败: {e}"


def _search_ddg(query: str, max_results: int) -> Tuple[Optional[str], Optional[str]]:
    """DuckDuckGo (via ddgs 库)"""

    if not _rate_limiters["ddg"].acquire():
        return None, "DuckDuckGo 限流，请稍后重试"

    try:
        from ddgs import DDGS

        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))

        if not results:
            return None, "DuckDuckGo 未找到结果"

        formatted = []
        for i, r in enumerate(results):
            formatted.append(f"{i+1}. {r['title']}\n   {r['href']}\n   {r['body']}")

        _backend_stats["ddg"]["success"] += 1
        return "\n\n".join(formatted), None

    except Exception as e:
        _backend_stats["ddg"]["failure"] += 1
        return None, f"DuckDuckGo 失败: {e}"


# ══════════════════════════════════════════════════
# 主搜索入口（后端回退链 + 缓存 + 熔断集成）
# ══════════════════════════════════════════════════

def web_search(query: str, max_results: int = 5, backend: Optional[str] = None) -> str:
    """执行联网搜索，支持多后端自动回退

    回退链: Brave → Serper → DuckDuckGo
    指定 backend 则仅使用该后端
    结果缓存 300s
    """
    if not _enabled:
        return "联网搜索功能未启用。如需使用，请在对话中开启 web_search 选项。"

    if not query or not query.strip():
        return "错误: 未提供搜索关键词"

    # 缓存检查
    cache_key = f"{query}:{max_results}:{backend or 'auto'}"
    cached = _search_cache.get(cache_key)
    if cached is not None:
        return cached

    backends: List[Tuple[str, callable]] = []
    if backend:
        bmap = {"brave": _search_brave, "serper": _search_serper, "ddg": _search_ddg}
        if backend in bmap:
            backends = [(backend, bmap[backend])]
        else:
            return f"未知搜索后端: {backend}。可用: brave, serper, ddg"
    else:
        backends = [
            ("brave", _search_brave),
            ("serper", _search_serper),
            ("ddg", _search_ddg),
        ]

    errors: List[str] = []
    for name, func in backends:
        try:
            result, error = func(query, max_results)
            if result is not None:
                _search_cache.set(cache_key, result)
                return result
            if error:
                errors.append(f"[{name}] {error}")
        except Exception as e:
            errors.append(f"[{name}] 异常: {e}")

    error_summary = "; ".join(errors) if errors else "所有搜索后端均未返回结果"
    logger.warning(f"web_search 全部后端失败: {error_summary}")
    return f"搜索失败：{error_summary}"
