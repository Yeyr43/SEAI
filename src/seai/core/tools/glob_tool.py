"""
glob_tool — 文件模式匹配工具 (Rust walkdir 加速)

两层回退: Rust FileOps.glob → Pure Python Path.glob
"""
import asyncio
from pathlib import Path
from typing import Dict, Any


async def execute(args: Dict[str, Any]) -> str:
    pattern = args.get("pattern", "**/*")
    path = args.get("path", ".")
    max_results = int(args.get("max_results", 200))

    # L1: Rust walkdir glob
    try:
        from .._rust import is_rust_available, get_file_ops
        if is_rust_available():
            result = get_file_ops().glob(pattern, path, max_results)
            if not result.startswith("[file_ops] 未找到"):
                return result
    except Exception:
        pass

    # L2: Pure Python
    search_dir = Path(path).resolve()
    if not search_dir.exists():
        return f"目录不存在: {path}"

    if not search_dir.is_dir():
        files = list(search_dir.parent.glob(search_dir.name))
    else:
        files = list(search_dir.glob(pattern))

    files = [f for f in files if f.is_file()]
    files.sort(key=lambda f: f.stat().st_mtime, reverse=True)

    if len(files) > max_results:
        truncated = files[:max_results]
        lines = [f"[共 {len(files)} 个文件，仅显示前 {max_results}]"]
        for f in truncated:
            size_kb = f.stat().st_size // 1024
            lines.append(f"{f.relative_to(search_dir) if search_dir.is_dir() else f}  ({size_kb} KB)")
        return "\n".join(lines)

    if not files:
        return f"(无匹配文件) pattern={pattern}, path={path}"

    lines = [f"找到 {len(files)} 个文件:"]
    for f in files:
        size_kb = f.stat().st_size // 1024
        size_str = f"{size_kb} KB" if size_kb > 0 else f"{f.stat().st_size} B"
        lines.append(f"{f.relative_to(search_dir) if search_dir.is_dir() else f}  ({size_str})")
    return "\n".join(lines)


def get_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "glob",
            "description": "使用 glob 模式搜索文件。支持递归搜索（如 **/*.py），结果按修改时间降序排列。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "glob 模式，如 '**/*.py', 'src/**/*.ts', '*.json'"},
                    "path": {"type": "string", "description": "搜索根目录", "default": "."},
                    "max_results": {"type": "integer", "description": "最多返回的文件数", "default": 200},
                },
                "required": ["pattern"]
            }
        }
    }
