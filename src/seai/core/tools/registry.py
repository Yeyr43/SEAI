# ══════════════════════════════════════════════════
# core/tool_registry.py - 工具注册表（适配接口版本）
# 功能：注册和管理所有内置工具，实现 ToolExecutor 接口
# ══════════════════════════════════════════════════
import ast, operator as ops, os
import asyncio
import subprocess
import shutil
from pathlib import Path
from typing import Callable, Dict, List, Any, Optional
import httpx
from .interfaces.tool_executor import ToolExecutor
from .tool_cache import tool_cache
from .circuit_breaker import breaker_manager
from .error_handler import SmartErrorHandler
from .tools import grep_execute, glob_execute, edit_execute, bash_execute, todo_execute, web_search_execute
from .tools.grep_tool import get_definition as grep_def
from .tools.glob_tool import get_definition as glob_def
from .tools.edit_tool import get_definition as edit_def
from .tools.bash_tool import get_definition as bash_def
from .tools.todo_tool import get_definition as todo_def
from .tools.web_search_tool import get_definition as web_search_def
from seai.se_tool import encode_image_to_base64, encode_audio_to_base64, get_image_info as get_img_info

def safe_calculator(expr: str) -> str:
    allowed = {ast.Add: ops.add, ast.Sub: ops.sub, ast.Mult: ops.mul, ast.Div: ops.truediv, ast.USub: ops.neg}
    def _eval(node):
        if isinstance(node, ast.Constant): return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub): return -_eval(node.operand)
        if isinstance(node, ast.BinOp): return allowed[type(node.op)](_eval(node.left), _eval(node.right))
        raise ValueError("不支持")
    return str(_eval(ast.parse(expr, mode='eval').body))


async def _execute_python(args: dict) -> str:
    """在安全沙箱中执行 Python 代码并返回结果"""
    from .sandbox import SandboxExecutor
    import tempfile

    code = args.get("code", "")
    timeout = int(args.get("timeout", 30))
    if not code or not code.strip():
        return "错误: 未提供代码"

    workspace = Path(tempfile.gettempdir()) / "seai_sandbox"
    workspace.mkdir(parents=True, exist_ok=True)
    sandbox = SandboxExecutor(workspace)

    try:
        stdout, stderr, returncode = await sandbox.execute_python(code, timeout=timeout)
    except Exception as e:
        return f"沙箱执行异常: {str(e)}"

    parts = []
    if stdout and stdout.strip():
        parts.append(f"[stdout]\n{stdout.rstrip()}")
    if stderr and stderr.strip():
        parts.append(f"[stderr]\n{stderr.rstrip()}")
    parts.append(f"[returncode: {returncode}]")
    return "\n\n".join(parts) if parts else "(无输出)"

class ToolRegistry(ToolExecutor):
    """工具注册表（实现 ToolExecutor 接口）"""

    MAX_READ_SIZE = 10 * 1024 * 1024   # 读取上限 10MB
    MAX_WRITE_SIZE = 5 * 1024 * 1024   # 写入上限 5MB
    MAX_LIST_ITEMS = 500               # 目录列表上限

    def __init__(self, security=None, error_handler: Optional[SmartErrorHandler] = None,
                 permission_manager=None, hook_manager=None):
        self._tools: Dict[str, Callable] = {}
        self._definitions: List[Dict] = []
        self.security = security
        self._error_handler = error_handler
        self._permission_manager = permission_manager
        self._hook_manager = hook_manager
        self._register_defaults()

    def _register_defaults(self):
        self.register("echo", lambda args: args.get("message",""), "返回消息")
        self.register("calculator", lambda args: safe_calculator(args.get("expression","0")), "计算", {"type":"object","properties":{"expression":{"type":"string"}}})
        self.register("read_file", self._read_file, "读取文件", {"type":"object","properties":{"path":{"type":"string"}},"required":["path"]})
        self.register("write_file", self._write_file, "写入文件（支持 test 参数）", {"type":"object","properties":{"path":{"type":"string"},"content":{"type":"string"},"test":{"type":"boolean","default":False}},"required":["path","content"]})
        self.register("delete_file", self._delete_file, "删除文件", {"type":"object","properties":{"path":{"type":"string"}},"required":["path"]})
        self.register("list_files", self._list_files, "列出目录", {"type":"object","properties":{"directory":{"type":"string"}},"required":["directory"]})
        self.register("fetch_url", self._fetch_url, "获取网页", {"type":"object","properties":{"url":{"type":"string"}},"required":["url"]})
        self.register("web_search", web_search_execute, "联网搜索（多后端自动回退：Brave → Serper → DuckDuckGo，结果缓存 300s）", web_search_def()["function"]["parameters"])
        self.register("encode_image", lambda args: encode_image_to_base64(args.get("path","")) or "图片编码失败", "将图片文件编码为 base64（支持 jpg/png/gif/webp/bmp）", {"type":"object","properties":{"path":{"type":"string","description":"图片文件路径"}},"required":["path"]})
        self.register("encode_audio", lambda args: encode_audio_to_base64(args.get("path","")) or "音频编码失败", "将音频文件编码为 base64（支持 wav/mp3/ogg/flac/m4a）", {"type":"object","properties":{"path":{"type":"string","description":"音频文件路径"}},"required":["path"]})
        self.register("get_image_info", lambda args: str(get_img_info(args.get("path","")) or {}), "获取图片信息（尺寸、格式等）", {"type":"object","properties":{"path":{"type":"string","description":"图片文件路径"}},"required":["path"]})
        self.register("execute_python", _execute_python, "在安全沙箱中执行 Python 代码并返回 stdout/stderr/returncode。可用于数学计算、数据处理、逻辑验证等。代码中可 import math/statistics/re/collections/itertools/json/datetime 等安全模块。", {"type":"object","properties":{"code":{"type":"string","description":"要执行的 Python 代码"},"timeout":{"type":"integer","description":"超时秒数，默认30","default":30}},"required":["code"]})
        self.register("execute_command", self._execute_command, "执行系统命令并返回 stdout/stderr/returncode。用于运行 shell 命令、调用外部程序等。命令必须通过安全策略白名单验证。", {"type":"object","properties":{"command":{"type":"string","description":"要执行的 shell 命令"},"timeout":{"type":"integer","description":"超时秒数，默认30","default":30}},"required":["command"]})
        # 专业开发工具
        self.register("grep", grep_execute, "基于 ripgrep 的内容搜索工具。支持正则表达式、文件类型过滤、上下文行数。", grep_def()["function"]["parameters"])
        self.register("glob", glob_execute, "使用 glob 模式搜索文件。支持递归搜索，结果按修改时间降序排列。", glob_def()["function"]["parameters"])
        self.register("edit", edit_execute, "基于精确字符串替换的文件编辑。要求 old_string 唯一匹配（或指定 replace_all）。", edit_def()["function"]["parameters"])
        self.register("bash", bash_execute, "安全 shell 命令执行。默认超时 120s，最大 600s。危险命令自动拦截。", bash_def()["function"]["parameters"])
        self.register("todo", todo_execute, "创建和管理任务列表。每个任务包含状态(pending/in_progress/completed)、描述和备注。", todo_def()["function"]["parameters"])

    def _check(self, path, mode="r"): return self.security.check_file_access(path, mode) if self.security else True

    def _read_file(self, args):
        path = args["path"]
        if not self._check(path, "r"): return "权限不足"
        p = Path(path)
        fsize = p.stat().st_size
        if fsize > self.MAX_READ_SIZE:
            # 大文件截断读取：头部 + 尾部，中间省略
            head_size = self.MAX_READ_SIZE // 2
            tail_size = head_size
            with open(p, "r", encoding="utf-8", errors="replace") as f:
                head = f.read(head_size)
                f.seek(max(fsize - tail_size, head_size))
                tail = f.read(tail_size)
            return f"{head}\n\n...[文件过大，省略 {fsize - head_size - tail_size} 字节]...\n\n{tail}"
        return p.read_text("utf-8", errors="replace")

    def _write_file(self, args):
        path, content = args["path"], args["content"]
        if not self._check(path, "w"): return "权限不足"
        content_bytes = content.encode("utf-8")
        if len(content_bytes) > self.MAX_WRITE_SIZE:
            return f"写入失败：内容大小 {len(content_bytes)} 字节超出上限 {self.MAX_WRITE_SIZE} 字节，请分割后分批写入"
        Path(path).write_text(content, "utf-8")
        if path.endswith(".py") and args.get("test", False):
            import subprocess
            try:
                result = subprocess.run(["python", path], capture_output=True, text=True, timeout=10)
                return f"写入成功且运行通过：{result.stdout[:200]}" if result.returncode == 0 else f"写入成功但运行失败：{result.stderr}"
            except subprocess.TimeoutExpired: return "写入成功但运行超时"
        return "写入成功"

    def _delete_file(self, args):
        path = args["path"]
        if not self._check(path, "w"): return "权限不足"
        p = Path(path)
        fsize = p.stat().st_size
        os.remove(path)
        return f"删除成功（{fsize} 字节）"

    def _list_files(self, args):
        directory = args["directory"]
        if not self._check(directory, "r"): return "权限不足"
        items = os.listdir(directory)
        if len(items) > self.MAX_LIST_ITEMS:
            return "\n".join(items[:self.MAX_LIST_ITEMS]) + f"\n\n...[共 {len(items)} 项，仅显示前 {self.MAX_LIST_ITEMS} 项]..."
        return "\n".join(items)

    def _execute_command(self, args):
        command = args.get("command", "").strip()
        timeout = int(args.get("timeout", 30))
        if not command:
            return "错误: 未提供命令"
        if self.security and not self.security.check_command(command):
            return f"命令被安全策略拒绝: {command}"
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=timeout, cwd=str(self.security.workspace) if self.security else None
            )
            parts = []
            if result.stdout and result.stdout.strip():
                parts.append(result.stdout.rstrip())
            if result.stderr and result.stderr.strip():
                parts.append(f"[stderr]\n{result.stderr.rstrip()}")
            parts.append(f"[returncode: {result.returncode}]")
            return "\n\n".join(parts) if parts else "(无输出)"
        except subprocess.TimeoutExpired:
            return f"命令执行超时 ({timeout}s): {command}"
        except Exception as e:
            return f"命令执行异常: {str(e)}"

    def _fetch_url(self, args):
        try:
            with httpx.Client(timeout=10, follow_redirects=True) as c: return c.get(args["url"]).text[:5000]
        except Exception as e: return f"获取失败：{e}"

    def register(self, name, func, desc="", params=None):
        self._tools[name] = func
        self._definitions.append({"type":"function","function":{"name":name,"description":desc,"parameters":params or {"type":"object","properties":{}}}})

    def get_tool_definitions(self): return self._definitions

    async def execute_tool(self, name: str, arguments: Dict[str, Any], agent_id: str = None) -> str:
        """执行工具（实现接口方法，带熔断保护 + 权限检查 + Hooks + 智能错误处理）"""
        if name not in self._tools:
            raise ValueError(f"工具 {name} 不存在")

        # 权限检查
        if self._permission_manager and agent_id:
            if not self._permission_manager.check_tool(agent_id, name):
                return f"权限拒绝: Agent [{agent_id}] 无权使用工具 {name}"
            if name in ("bash", "execute_command") and name in arguments:
                if not self._permission_manager.check_bash(agent_id, arguments.get("command", "")):
                    return f"权限拒绝: Agent [{agent_id}] 的 bash 命令被拒绝"

        tool_breaker = breaker_manager.get_or_create(f"tool_{name}", failure_threshold=5, cooldown_seconds=60.0)
        if not tool_breaker.can_execute():
            return f"工具 {name} 暂时不可用（熔断保护已触发），请稍后重试"

        cacheable = name in ("read_file", "list_files", "web_search", "echo", "calculator", "grep", "glob", "get_image_info")
        if cacheable:
            cached = tool_cache.get(name, arguments)
            if cached is not None:
                return cached

        # pre_tool hooks
        if self._hook_manager:
            hook_outputs = await self._hook_manager.trigger(
                "pre_tool", tool_name=name, tool_args=arguments, filepath=arguments.get("path", arguments.get("file_path", ""))
            )
            if hook_outputs:
                logger.debug(f"pre_tool hooks: {hook_outputs}")

        try:
            func = self._tools[name]
            result = func(arguments)
            if asyncio.iscoroutine(result):
                result = await result
            tool_breaker.on_success()
        except FileNotFoundError as e:
            tool_breaker.on_failure()
            if self._error_handler:
                diagnosis = self._error_handler.handle_error(e, {"tool": name, "args": str(arguments)[:200]})
                return f"文件未找到: {diagnosis.immediate_fix}"
            raise
        except PermissionError as e:
            tool_breaker.on_failure()
            if self._error_handler:
                diagnosis = self._error_handler.handle_error(e, {"tool": name, "args": str(arguments)[:200]})
                return f"权限不足: {diagnosis.immediate_fix}"
            raise
        except (ConnectionError, TimeoutError) as e:
            tool_breaker.on_failure()
            if self._error_handler:
                diagnosis = self._error_handler.handle_error(e, {"tool": name, "args": str(arguments)[:200]})
                return f"连接失败: {diagnosis.immediate_fix}"
            raise
        except ValueError as e:
            tool_breaker.on_failure()
            if self._error_handler:
                diagnosis = self._error_handler.handle_error(e, {"tool": name, "args": str(arguments)[:200]})
                return f"参数错误: {diagnosis.immediate_fix}"
            raise
        except MemoryError as e:
            tool_breaker.on_failure()
            if self._error_handler:
                diagnosis = self._error_handler.handle_error(e, {"tool": name, "args": str(arguments)[:200]})
                return f"内存不足: {diagnosis.immediate_fix}"
            raise
        except Exception as e:
            tool_breaker.on_failure()
            if self._error_handler:
                diagnosis = self._error_handler.handle_error(e, {"tool": name, "args": str(arguments)[:200]})
                return f"工具执行异常 [{diagnosis.error_type}]: {diagnosis.immediate_fix}"
            raise

        if cacheable:
            tool_cache.set(name, arguments, result)

        # post_tool hooks
        if self._hook_manager:
            asyncio.create_task(self._hook_manager.trigger(
                "post_tool", tool_name=name, tool_args=arguments, tool_result=str(result),
                filepath=arguments.get("path", arguments.get("file_path", ""))
            ))

        return result
    
    async def execute(self, name, args):
        """兼容旧版本的方法"""
        return await self.execute_tool(name, args)
    
    def get_tool_definitions(self) -> List[Dict]:
        """获取工具定义列表（实现接口方法）"""
        return self._definitions
    
    def register_tool(self, name: str, func, description: str = "", params: Dict = None):
        """注册工具（实现接口方法）"""
        self.register(name, func, description, params)
    
    def unregister_tool(self, name: str):
        """注销工具（实现接口方法）"""
        if name in self._tools:
            del self._tools[name]
            self._definitions = [d for d in self._definitions 
                               if d.get("function", {}).get("name") != name]
    
    def get_available_tools(self) -> List[str]:
        """获取可用工具列表（实现接口方法）"""
        return list(self._tools.keys())
    
    def validate_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> bool:
        """验证工具调用（实现接口方法）"""
        if tool_name not in self._tools:
            return False
        
        # 这里可以添加更复杂的验证逻辑
        return True