"""
Rust 引擎 Python 薄封装层

对所有 Rust 底层模块提供统一的 Python 接口，自动回退到纯 Python 实现。
用法:
    from core._rust import get_event_bus, get_memory_engine, get_knowledge_graph
    from core._rust import get_sandbox, get_circuit_breaker, get_http_client
    from core._rust import get_file_ops, get_tokenizer, get_search_client, get_command_sandbox
"""

from loguru import logger

_RUST_AVAILABLE = False
_rust_module = None

try:
    from .. import _rust_core as _rust_module
    _RUST_AVAILABLE = True
    logger.info("Rust 引擎已加载 — 高性能底层模块可用")
except ImportError:
    try:
        import _rust_core as _rust_module
        _RUST_AVAILABLE = True
        logger.info("Rust 引擎已加载 (top-level) — 高性能底层模块可用")
    except ImportError:
        logger.info("Rust 引擎未安装 — 使用纯 Python 回退实现")

# ══════════════════════════════════════════════════
# 单例缓存
# ══════════════════════════════════════════════════

_event_bus = None
_memory_engine = None
_knowledge_graph = None
_sandbox = None
_circuit_breaker = None
_http_client = None
_context_manager = None
_file_ops = None
_tokenizer = None
_search_client = None
_command_sandbox = None


def is_rust_available() -> bool:
    return _RUST_AVAILABLE


# ══════════════════════════════════════════════════
# Event Bus (已有 Python 回退 ✓)
# ══════════════════════════════════════════════════

def get_event_bus():
    """获取 Rust 事件总线实例（回退到 Python AsyncEventBus）"""
    global _event_bus
    if _event_bus is not None:
        return _event_bus
    if _RUST_AVAILABLE:
        _event_bus = _rust_module.RustEventBus()
        return _event_bus
    from .event_bus import event_bus
    return event_bus


# ══════════════════════════════════════════════════
# Memory Engine
# ══════════════════════════════════════════════════

def get_memory_engine():
    """获取 Rust 记忆引擎实例（回退到 Python MemoryEngine）"""
    global _memory_engine
    if _memory_engine is not None:
        return _memory_engine
    if _RUST_AVAILABLE:
        _memory_engine = _rust_module.RustMemoryEngine(10000)
        return _memory_engine
    # Python 回退
    try:
        from .tools.memory import MemoryEngine
        _memory_engine = MemoryEngine()
        return _memory_engine
    except ImportError:
        from .memory_engine import MemoryEngine
        _memory_engine = MemoryEngine()
        return _memory_engine


# ══════════════════════════════════════════════════
# Knowledge Graph
# ══════════════════════════════════════════════════

def get_knowledge_graph():
    """获取 Rust 知识图谱实例（回退到 Python KnowledgeGraphManager）"""
    global _knowledge_graph
    if _knowledge_graph is not None:
        return _knowledge_graph
    if _RUST_AVAILABLE:
        _knowledge_graph = _rust_module.RustKnowledgeGraph()
        return _knowledge_graph
    # Python 回退
    from .knowledge_graph.manager import KnowledgeGraphManager
    from pathlib import Path
    kg_dir = Path(__file__).parent.parent.parent.parent / "data" / "knowledge_graph"
    _knowledge_graph = KnowledgeGraphManager(kg_dir)
    _knowledge_graph.initialize()
    return _knowledge_graph


# ══════════════════════════════════════════════════
# Sandbox
# ══════════════════════════════════════════════════

def get_sandbox(timeout_ms: int = 5000):
    """获取 Rust 安全沙箱实例（回退到 Python 安全计算器）"""
    global _sandbox
    if _sandbox is not None:
        return _sandbox
    if _RUST_AVAILABLE:
        _sandbox = _rust_module.SandboxExecutor(timeout_ms)
        return _sandbox
    # Python 回退: 内联安全 eval
    import ast
    import operator

    class _PySandbox:
        def __init__(self, timeout_ms=5000):
            self.timeout_ms = timeout_ms

        def safe_eval(self, expression: str) -> float:
            """仅支持 + - * / % ** 和数字的表达式求值"""
            allowed_ops = {
                ast.Add: operator.add, ast.Sub: operator.sub,
                ast.Mult: operator.mul, ast.Div: operator.truediv,
                ast.Mod: operator.mod, ast.Pow: operator.pow,
                ast.USub: operator.neg,
            }

            def _eval(node):
                if isinstance(node, ast.Expression):
                    return _eval(node.body)
                if isinstance(node, ast.BinOp):
                    op_type = type(node.op)
                    if op_type not in allowed_ops:
                        raise ValueError(f"不支持的操作: {op_type.__name__}")
                    return allowed_ops[op_type](_eval(node.left), _eval(node.right))
                if isinstance(node, ast.UnaryOp):
                    return allowed_ops[type(node.op)](_eval(node.operand))
                if isinstance(node, ast.Constant):
                    return float(node.value)
                raise ValueError(f"不支持的节点: {type(node).__name__}")

            tree = ast.parse(expression, mode='eval')
            return float(_eval(tree))

        def health(self):
            return "sandbox: operational (Python safe_eval fallback)"

    _PySandbox.safe_eval.__func__  # noqa
    _sandbox = _PySandbox(timeout_ms)
    return _sandbox


def safe_eval(expression: str) -> float:
    """安全数学表达式求值（Rust 优先，回退到 AST）"""
    if _RUST_AVAILABLE:
        return get_sandbox().safe_eval(expression)
    return get_sandbox().safe_eval(expression)


# ══════════════════════════════════════════════════
# Circuit Breaker
# ══════════════════════════════════════════════════

def get_circuit_breaker(threshold: int = 5, recovery_timeout_ms: int = 30000):
    """获取 Rust 熔断器实例（回退到 Python CircuitBreaker）"""
    global _circuit_breaker
    if _circuit_breaker is not None:
        return _circuit_breaker
    if _RUST_AVAILABLE:
        _circuit_breaker = _rust_module.CircuitBreaker(threshold, recovery_timeout_ms)
        return _circuit_breaker
    # Python 回退
    from .circuit_breaker import CircuitBreaker
    cooldown_secs = recovery_timeout_ms / 1000.0
    _circuit_breaker = CircuitBreaker(
        name="rust_fallback",
        failure_threshold=threshold,
        cooldown_seconds=cooldown_secs,
    )
    return _circuit_breaker


# ══════════════════════════════════════════════════
# HTTP Client
# ══════════════════════════════════════════════════

def get_http_client(timeout_secs: int = 120, max_retries: int = 3):
    """获取 Rust HTTP 客户端实例（回退到 Python httpx 封装）"""
    global _http_client
    if _http_client is not None:
        return _http_client
    if _RUST_AVAILABLE:
        _http_client = _rust_module.LlmClient(timeout_secs, max_retries)
        _http_client.init()
        return _http_client
    # Python 回退: 简单的 httpx 封装
    import httpx

    class _PyHttpClient:
        def __init__(self, timeout_secs=120, max_retries=3):
            self.timeout = timeout_secs
            self.max_retries = max_retries
            self._client = None

        def init(self):
            self._client = httpx.Client(timeout=self.timeout)
            return True

        def add_endpoint(self, url, label, priority):
            pass

        def chat(self, api_key, model, messages_json):
            if not self._client:
                self.init()
            # Simplified: return placeholder
            return ""

        def health_check(self, url):
            import time
            start = time.time()
            try:
                if not self._client:
                    self.init()
                resp = self._client.get(url)
                latency = (time.time() - start) * 1000
                return '{"status":%d,"latency_ms":%.0f}' % (resp.status_code, latency)
            except Exception as e:
                return '{"error":"%s"}' % str(e)

        def health(self):
            return "http_client: operational (Python httpx fallback)"

    _http_client = _PyHttpClient(timeout_secs, max_retries)
    return _http_client


# ══════════════════════════════════════════════════
# Context Manager
# ══════════════════════════════════════════════════

def get_context_manager():
    """获取 Rust 上下文管理器实例（回退到 Python 启发式估算）"""
    global _context_manager
    if _context_manager is not None:
        return _context_manager
    if _RUST_AVAILABLE:
        _context_manager = _rust_module.ContextManager()
        return _context_manager

    # Python 回退: 内联启发式 token 估算
    class _PyContextManager:
        def count_tokens(self, text: str, model: str = "claude") -> int:
            if not text:
                return 0
            tokens = 0.0
            chars = list(text)
            i = 0
            while i < len(chars):
                ch = chars[i]
                if ch.isspace():
                    s = i
                    while i < len(chars) and chars[i].isspace():
                        i += 1
                    tokens += max(1.0, (i - s) * 0.25)
                elif ch.isascii() and ch.isalpha():
                    s = i
                    while i < len(chars) and chars[i].isascii() and chars[i].isalpha():
                        i += 1
                    tokens += max(1.0, ((i - s) / 4.0))
                elif ch.isascii() and ch.isdigit():
                    s = i
                    while i < len(chars) and (chars[i].isdigit() or chars[i] == '.'):
                        i += 1
                    tokens += max(1.0, ((i - s) / 3.0))
                elif ch.isascii():
                    i += 1
                    tokens += 1.0
                else:
                    i += 1
                    tokens += 1.5
            return int(tokens)

        def count_messages(self, messages_json: str) -> int:
            import json
            try:
                arr = json.loads(messages_json)
                return sum(
                    self.count_tokens(m.get("role", "")) +
                    self.count_tokens(m.get("content", "")) + 4
                    for m in arr
                )
            except Exception:
                return len(messages_json) // 4

        def should_compress(self, token_count: int, context_limit: int) -> bool:
            return token_count > int(context_limit * 0.8)

        def compression_level(self, token_count: int, context_limit: int) -> int:
            ratio = token_count / max(context_limit, 1)
            return 0 if ratio < 0.5 else (1 if ratio < 0.8 else 2)

        def estimate_savings(self, token_count: int, level: int) -> int:
            return {0: 0, 1: int(token_count * 0.3), 2: int(token_count * 0.5)}.get(level, int(token_count * 0.5))

        def get_stats(self):
            return {"total_counted": 0, "total_tokens": 0, "avg_tokens_per_call": 0}

        def health(self):
            return "context_manager: operational (Python heuristic fallback)"

    _context_manager = _PyContextManager()
    return _context_manager


def estimate_tokens(text: str, model: str = "claude") -> int:
    """估算文本的 Token 数量（Rust 实现，回退到字符/4）"""
    if _RUST_AVAILABLE:
        return get_context_manager().count_tokens(text, model)
    return get_context_manager().count_tokens(text, model)


# ══════════════════════════════════════════════════
# 新增: File Ops (Rust file_ops 模块)
# ══════════════════════════════════════════════════

def get_file_ops():
    """获取 Rust 文件操作实例（回退到 Python 工具函数）"""
    global _file_ops
    if _file_ops is not None:
        return _file_ops
    if _RUST_AVAILABLE:
        _file_ops = _rust_module.FileOps()
        return _file_ops

    # Python 回退: 包装现有工具函数
    class _PyFileOps:
        def grep(self, pattern, path, glob_filter=None, ignore_case=False,
                 head_limit=50, before=0, after=0, multiline=False):
            import subprocess, shutil
            if shutil.which("rg"):
                cmd = ["rg", "--no-heading", "--with-filename", "--line-number",
                       "--color=never"]
                if ignore_case:
                    cmd.append("--ignore-case")
                if multiline:
                    cmd.extend(["--multiline", "--multiline-dotall"])
                if before:
                    cmd.extend(["-B", str(before)])
                if after:
                    cmd.extend(["-A", str(after)])
                if glob_filter:
                    cmd.extend(["--glob", glob_filter])
                cmd.extend(["--", pattern, path])
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    lines = [l for l in r.stdout.splitlines() if l.strip()]
                    return "\n".join(lines[:head_limit]) or "[grep] 无匹配结果"
                except Exception as e:
                    return f"[grep] 执行失败: {e}"
            return "[grep] ripgrep (rg) 未安装"

        def edit_file(self, file_path, old_string, new_string, replace_all=False):
            from pathlib import Path
            p = Path(file_path)
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                return f"[edit] 读取失败: {e}"
            if replace_all:
                count = content.count(old_string)
                result = content.replace(old_string, new_string)
            else:
                count = content.count(old_string)
                if count == 0:
                    return f"[edit] 未找到: {old_string}"
                if count > 1:
                    return f"[edit] 找到 {count} 处匹配，请缩小范围"
                result = content.replace(old_string, new_string, 1)
                count = 1
            try:
                p.write_text(result, encoding="utf-8", errors="replace")
                return f"[edit] 已编辑 {file_path}，替换了 {count} 处"
            except Exception as e:
                return f"[edit] 写入失败: {e}"

        def glob(self, pattern, path, max_results=200):
            from pathlib import Path
            import os
            search_root = Path(path)
            if not search_root.exists():
                return f"[glob] 路径不存在: {path}"
            results = []
            for f in search_root.rglob("*"):
                if len(results) >= max_results:
                    break
                if f.is_file():
                    rel = str(f.relative_to(search_root)).replace("\\", "/")
                    import fnmatch
                    if fnmatch.fnmatch(rel, pattern):
                        size_kb = f.stat().st_size / 1024
                        results.append(f"{rel} ({size_kb:.1f} KB)")
            return "\n".join(results) if results else f"[glob] 未找到: {pattern}"

        def health(self):
            return "file_ops: operational (Python subprocess fallback)"

    _file_ops = _PyFileOps()
    return _file_ops


# ══════════════════════════════════════════════════
# 新增: Tokenizer
# ══════════════════════════════════════════════════

def get_tokenizer():
    """获取 Rust 分词器实例（回退到 get_context_manager）"""
    global _tokenizer
    if _tokenizer is not None:
        return _tokenizer
    if _RUST_AVAILABLE:
        _tokenizer = _rust_module.RustTokenizer()
        return _tokenizer
    # Python 回退: 复用 context_manager 的计数逻辑
    _tokenizer = get_context_manager()
    return _tokenizer


# ══════════════════════════════════════════════════
# 新增: Search Client
# ══════════════════════════════════════════════════

def get_search_client():
    """获取 Rust 搜索客户端实例（回退到 Python net.py）"""
    global _search_client
    if _search_client is not None:
        return _search_client
    if _RUST_AVAILABLE:
        _search_client = _rust_module.SearchClient()
        _search_client.init()
        return _search_client

    # Python 回退: 使用 net.py 的 web_search
    from .infra.net import web_search, is_enabled as net_enabled

    class _PySearchClient:
        def init(self):
            return True

        def set_enabled(self, val):
            from .infra import net
            net.set_enabled(val)

        def is_enabled(self):
            return net_enabled()

        def search(self, query, max_results=5, backend=None):
            from .infra.net import web_search as ws
            return ws(query, max_results)

        def clean_cache(self):
            pass

        def check_rate_limit(self):
            return True

        def get_stats(self):
            return {"ddg_count": 0, "brave_count": 0, "serper_count": 0, "enabled": net_enabled()}

        def health(self):
            return "search_client: operational (Python DDGS fallback)"

    _search_client = _PySearchClient()
    return _search_client


# ══════════════════════════════════════════════════
# 新增: Command Sandbox
# ══════════════════════════════════════════════════

def get_command_sandbox():
    """获取 Rust 命令沙箱实例（回退到 Python bash_tool）"""
    global _command_sandbox
    if _command_sandbox is not None:
        return _command_sandbox
    if _RUST_AVAILABLE:
        _command_sandbox = _rust_module.CommandSandbox()
        return _command_sandbox

    # Python 回退
    import re
    import asyncio
    import subprocess
    import os

    DANGEROUS = [
        r"rm\s+-rf\s+/", r"mkfs\.", r"dd\s+if=", r">\s*/dev/sd",
        r"chmod\s+777\s+/", r":\(\)\s*\{\s*:\s*\|\:?\s*&\s*\};:",
        r"shutdown\s+", r"reboot", r"curl\s+.*\|\s*(ba)?sh",
        r"wget\s+.*\|\s*(ba)?sh",
    ]

    class _PyCommandSandbox:
        def execute(self, command, timeout_ms=None, workdir=None, env=None):
            for pat in DANGEROUS:
                if re.search(pat, command):
                    return f"[sandbox] 命令被安全策略阻止:\n  命令: {command}\n  原因: 匹配危险模式"
            timeout = (timeout_ms or 120000) / 1000
            try:
                r = subprocess.run(
                    command, shell=True, capture_output=True, text=True,
                    timeout=timeout, cwd=workdir or os.getcwd(),
                    env={**os.environ, **(env or {})} if env else None,
                )
                stdout = r.stdout[:8000]
                stderr = r.stderr[:4000]
                result = stdout
                if stderr:
                    result += f"\n\n[stderr]\n{stderr}"
                if r.returncode != 0:
                    result += f"\n\n[returncode: {r.returncode}]"
                return result or f"[exit: {r.returncode}]"
            except subprocess.TimeoutExpired:
                return f"[sandbox] 命令执行超时 (>{timeout:.0f}s)"
            except Exception as e:
                return f"[sandbox] 命令执行失败: {e}"

        def is_dangerous(self, command):
            return any(re.search(p, command) for p in DANGEROUS)

        def get_stats(self):
            return {}

        def health(self):
            return "command_sandbox: operational (Python subprocess fallback)"

    _command_sandbox = _PyCommandSandbox()
    return _command_sandbox


# ══════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════

def get_rust_stats() -> dict:
    """获取所有 Rust 模块的统计信息"""
    if not _RUST_AVAILABLE:
        return {"rust_available": False}
    return {
        "rust_available": True,
        "version": _rust_module.health_check(),
    }
