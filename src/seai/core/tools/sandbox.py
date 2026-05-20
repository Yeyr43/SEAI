# ══════════════════════════════════════════════════
# core/sandbox.py - 增强沙箱执行器
# ══════════════════════════════════════════════════
import asyncio
import tempfile
import shutil
import os
import re
import sys
from pathlib import Path
from typing import Optional, Tuple, List

DANGEROUS_PATTERNS = [
    (r'os\.system\s*\(', 'os.system() 调用'),
    (r'subprocess\.(call|Popen|run|check_output)\s*\(', 'subprocess 调用'),
    (r'eval\s*\(', 'eval() 调用'),
    (r'exec\s*\(', 'exec() 调用'),
    (r'__import__\s*\(', '__import__() 调用'),
    (r'open\s*\([^)]*[\'"][wa]', '文件写入操作'),
    (r'shutil\.(rmtree|copytree|move)\s*\(', 'shutil 危险操作'),
    (r'os\.(remove|unlink|rmdir|chmod|chown)\s*\(', 'os 文件删除/权限操作'),
    (r'socket\.', 'socket 网络操作'),
    (r'requests\.(get|post|put|delete|patch)\s*\(', 'HTTP 请求'),
    (r'urllib\.', 'urllib 网络操作'),
    (r'ftplib\.', 'FTP 操作'),
    (r'import\s+ctypes', 'ctypes 导入'),
    (r'import\s+multiprocessing', 'multiprocessing 导入'),
    (r'import\s+threading', 'threading 导入'),
    (r'sys\.exit\s*\(', 'sys.exit() 调用'),
    (r'os\.(setuid|setgid|fork|kill)\s*\(', 'os 进程操作'),
]

ALLOWED_IMPORTS = {
    'math', 'json', 're', 'datetime', 'collections', 'itertools',
    'functools', 'typing', 'dataclasses', 'enum', 'copy', 'hashlib',
    'base64', 'binascii', 'csv', 'string', 'textwrap', 'unicodedata',
    'random', 'statistics', 'decimal', 'fractions', 'numbers',
    'pathlib', 'os.path', 'tempfile', 'io', 'contextlib',
    'operator', 'abc', 'warnings', 'traceback', 'pprint',
    'html', 'xml.etree.ElementTree', 'urllib.parse',
}


class CodeValidator:
    @staticmethod
    def validate(code: str) -> Tuple[bool, List[str]]:
        warnings = []
        for pattern, desc in DANGEROUS_PATTERNS:
            if re.search(pattern, code):
                warnings.append(f"检测到危险模式: {desc}")
        return len(warnings) == 0, warnings

    @staticmethod
    def sanitize(code: str) -> str:
        code = re.sub(r'__\w+__\s*=', '# BLOCKED_DUNDER_ASSIGN', code)
        return code


class SandboxExecutor:
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.validator = CodeValidator()

    def validate_code(self, code: str) -> Tuple[bool, List[str]]:
        return self.validator.validate(code)

    async def execute(
        self, cmd: str, timeout: int = 30, allow_network: bool = False,
        max_output_bytes: int = 1024 * 1024
    ) -> Tuple[str, str, int]:
        sandbox_dir = Path(tempfile.mkdtemp(prefix="seai_sandbox_"))

        env = os.environ.copy()
        env["PATH"] = os.environ.get("PATH", "")
        env["HOME"] = str(sandbox_dir)
        env["TMPDIR"] = str(sandbox_dir)
        env["TEMP"] = str(sandbox_dir)
        env["TMP"] = str(sandbox_dir)

        if not allow_network:
            for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY"):
                env[key] = ""
            env["PYTHONPATH"] = ""

        env.pop("PYTHONSTARTUP", None)
        env.pop("VIRTUAL_ENV", None)

        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(sandbox_dir),
                env=env,
                limit=max_output_bytes,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    pass
                return "", f"执行超时 ({timeout}s)", -1

            return (
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
                proc.returncode or 0,
            )
        except Exception as e:
            return "", f"沙箱执行异常: {str(e)}", -1
        finally:
            if sandbox_dir.exists():
                try:
                    shutil.rmtree(sandbox_dir, ignore_errors=True)
                except Exception:
                    pass

    async def execute_python(
        self, code: str, timeout: int = 30, allow_network: bool = False
    ) -> Tuple[str, str, int]:
        is_safe, warnings = self.validator.validate(code)
        if not is_safe:
            return "", "代码安全检查未通过:\n" + "\n".join(warnings), -1

        sanitized = self.validator.sanitize(code)

        sandbox_dir = Path(tempfile.mkdtemp(prefix="seai_sandbox_"))
        script_path = sandbox_dir / "_script.py"
        script_path.write_text(sanitized, encoding="utf-8")

        env = os.environ.copy()
        env["PATH"] = os.environ.get("PATH", "")
        env["HOME"] = str(sandbox_dir)
        env["TMPDIR"] = str(sandbox_dir)
        env["TEMP"] = str(sandbox_dir)
        env["TMP"] = str(sandbox_dir)

        if not allow_network:
            for key in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "no_proxy", "NO_PROXY"):
                env[key] = ""
            env["PYTHONPATH"] = ""

        env.pop("PYTHONSTARTUP", None)
        env.pop("VIRTUAL_ENV", None)

        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable, "-S", str(script_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(sandbox_dir),
                env=env,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except Exception:
                    pass
                return "", f"Python 代码执行超时 ({timeout}s)", -1

            return (
                stdout.decode("utf-8", errors="replace"),
                stderr.decode("utf-8", errors="replace"),
                proc.returncode or 0,
            )
        except Exception as e:
            return "", f"Python 沙箱执行异常: {str(e)}", -1
        finally:
            if sandbox_dir.exists():
                try:
                    shutil.rmtree(sandbox_dir, ignore_errors=True)
                except Exception:
                    pass