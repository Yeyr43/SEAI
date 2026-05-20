"""
bash_tool — 安全的 shell 命令执行工具 (Rust 沙箱加速)

两层回退: Rust CommandSandbox.execute → Python subprocess
"""
import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Dict, Any

# 危险命令黑名单（正则模式）
_DANGEROUS_PATTERNS = [
    r"rm\s+(-rf?\s+)?/",           # rm -rf /
    r"mkfs\.",                       # 格式化文件系统
    r"dd\s+if=",                     # 磁盘写入
    r">\s*/dev/(sd|hd|nvme|mmc)",   # 写入块设备
    r"chmod\s+.*777",               # 全局可写
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:", # fork bomb
    r"shutdown\b",                   # 关机
    r"reboot\b",                     # 重启
    r"curl.*\|\s*(ba)?sh\b",        # curl pipe shell
    r"wget.*\|\s*(ba)?sh\b",        # wget pipe shell
]


async def execute(args: Dict[str, Any]) -> str:
    command = args.get("command", "").strip()
    timeout = min(int(args.get("timeout", 120)), 600)
    workdir = args.get("workdir", "")
    env_vars = args.get("env", {})

    if not command:
        return "错误: 未提供命令 (command)"

    # 安全检查 (Rust path handles this internally too)
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return f"命令被安全策略拒绝（匹配危险模式: {pattern}）: {command[:200]}"

    # L1: Rust CommandSandbox
    try:
        from .._rust import is_rust_available, get_command_sandbox
        if is_rust_available():
            result = get_command_sandbox().execute(
                command, timeout * 1000, workdir or None, env_vars or None
            )
            if not result.startswith("[sandbox] 命令执行失败"):
                return result
    except Exception:
        pass

    # L2: Python subprocess
    cwd = str(Path(workdir).resolve()) if workdir else None
    if cwd and not Path(cwd).exists():
        return f"工作目录不存在: {workdir}"

    env = os.environ.copy()
    env.update(env_vars)

    try:
        result = await asyncio.to_thread(
            subprocess.run,
            command, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=cwd, env=env
        )
    except subprocess.TimeoutExpired:
        return f"命令执行超时 ({timeout}s): {command[:200]}"
    except Exception as e:
        return f"命令执行异常: {str(e)}"

    parts = []
    if result.stdout and result.stdout.strip():
        stdout = result.stdout.rstrip()
        if len(stdout) > 8000:
            stdout = stdout[:8000] + "\n...[输出截断，总长度 {} 字符]...".format(len(result.stdout))
        parts.append(stdout)
    if result.stderr and result.stderr.strip():
        stderr = result.stderr.rstrip()
        if len(stderr) > 4000:
            stderr = stderr[:4000] + "\n...[stderr 截断]..."
        parts.append(f"[stderr]\n{stderr}")
    parts.append(f"[returncode: {result.returncode}]")
    return "\n\n".join(parts) if parts else "(无输出)"


def get_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "执行 shell 命令并返回 stdout/stderr/returncode。默认超时 120s，最大 600s。危险命令（如 rm -rf /、mkfs、fork bomb）会被自动拦截。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "要执行的 shell 命令"},
                    "timeout": {"type": "integer", "description": "超时秒数，默认120，最大600", "default": 120},
                    "workdir": {"type": "string", "description": "工作目录（绝对路径），默认当前目录"},
                    "env": {"type": "object", "description": "额外的环境变量，如 {'DEBUG': '1'}"},
                },
                "required": ["command"]
            }
        }
    }
