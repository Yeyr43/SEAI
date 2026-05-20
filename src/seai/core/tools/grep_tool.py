"""
grep_tool — 基于 ripgrep 的内容搜索工具 (Rust 加速 + ripgrep CLI + Python fallback)

三层回退: Rust FileOps → ripgrep CLI → Pure Python
"""
import subprocess
import shutil
from pathlib import Path
from typing import Dict, Any


async def execute(args: Dict[str, Any]) -> str:
    pattern = args.get("pattern", "")
    path = args.get("path", ".")
    glob_filter = args.get("glob", "")
    file_type = args.get("type", "")
    context_before = int(args.get("before", 0))
    context_after = int(args.get("after", 0))
    context = int(args.get("context", 0))
    ignore_case = args.get("ignore_case", False)
    head_limit = int(args.get("head_limit", 50))
    multiline = args.get("multiline", False)
    output_mode = args.get("output_mode", "content")

    if not pattern:
        return "错误: 未提供搜索模式 (pattern)"

    # L1: Rust FileOps.grep
    try:
        from .._rust import is_rust_available, get_file_ops
        if is_rust_available():
            result = get_file_ops().grep(
                pattern, path, glob_filter or None,
                ignore_case, head_limit,
                context_before or context or None,
                context_after or context or None,
                multiline,
            )
            if not result.startswith("[file_ops]"):
                return result
    except Exception:
        pass

    # L2: ripgrep CLI
    rg_path = shutil.which("rg")

    if rg_path:
        return _run_ripgrep(
            rg_path, pattern, path, glob_filter, file_type,
            context_before, context_after, context,
            ignore_case, head_limit, multiline, output_mode
        )
    # L3: Pure Python
    return _run_python_grep(
        pattern, path, glob_filter, file_type,
        context_before, context_after, context,
        ignore_case, head_limit, output_mode
    )


def _run_ripgrep(rg_path, pattern, path, glob_filter, file_type,
                 before, after, ctx, ignore_case, head_limit, multiline, output_mode):
    cmd = [rg_path, "--no-heading", "--with-filename", "--line-number", "--color=never"]
    if ignore_case:
        cmd.append("-i")
    if multiline:
        cmd.extend(["-U", "--multiline-dotall"])
    if glob_filter:
        cmd.extend(["-g", glob_filter])
    if file_type:
        cmd.extend(["-t", file_type])
    if ctx > 0:
        cmd.extend(["-C", str(ctx)])
    if before > 0:
        cmd.extend(["-B", str(before)])
    if after > 0:
        cmd.extend(["-A", str(after)])
    if output_mode == "files_with_matches":
        cmd.append("-l")
    elif output_mode == "count":
        cmd.append("-c")

    cmd.append("--")
    cmd.append(pattern)
    cmd.append(path)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=Path(path).resolve() if Path(path).is_dir() else None)
        output = (result.stdout or result.stderr or "(无匹配)").rstrip()
        lines = output.split("\n")
        if len(lines) > head_limit:
            output = "\n".join(lines[:head_limit]) + f"\n\n...[共 {len(lines)} 条匹配，仅显示前 {head_limit} 条]..."
        return output if output.strip() else "(无匹配)"
    except subprocess.TimeoutExpired:
        return f"搜索超时 (30s): pattern={pattern}, path={path}"
    except Exception as e:
        return f"搜索异常: {str(e)}"


def _run_python_grep(pattern, path, glob_filter, file_type,
                     before, after, ctx, ignore_case, head_limit, output_mode):
    """Python fallback grep — 在无法使用 ripgrep 时"""
    import re as _re
    import fnmatch
    from pathlib import Path as _Path

    try:
        flags = _re.IGNORECASE if ignore_case else 0
        regex = _re.compile(pattern, flags)
    except _re.error as e:
        return f"正则表达式错误: {str(e)}"

    search_path = _Path(path).resolve()
    if not search_path.exists():
        return f"路径不存在: {path}"

    # 确定扩展名过滤
    type_to_ext = {"py": ".py", "js": ".js", "ts": ".ts", "tsx": ".tsx",
                   "rs": ".rs", "go": ".go", "java": ".java", "c": ".c",
                   "cpp": ".cpp", "h": ".h", "css": ".css", "html": ".html",
                   "json": ".json", "yaml": ".yaml", "yml": ".yml",
                   "toml": ".toml", "md": ".md"}
    file_exts = None
    if file_type:
        file_exts = {type_to_ext.get(file_type, f".{file_type}")}

    context_lines = ctx or max(before, after)
    results = []
    files_checked = 0

    if search_path.is_file():
        files = [search_path]
    else:
        files = []
        for f in search_path.rglob("*"):
            if f.is_file():
                if glob_filter and not fnmatch.fnmatch(f.name, glob_filter):
                    continue
                if file_exts and f.suffix not in file_exts:
                    continue
                files.append(f)

    matched_files = set()

    for f in files:
        files_checked += 1
        try:
            content = f.read_text("utf-8", errors="replace")
        except Exception:
            continue
        lines_list = content.split("\n")
        for i, line in enumerate(lines_list):
            if regex.search(line):
                if output_mode == "count":
                    matched_files.add(str(f))
                    break
                if output_mode == "files_with_matches":
                    results.append(str(f))
                    break
                start = max(0, i - context_lines)
                end = min(len(lines_list), i + context_lines + 1)
                block = "\n".join(f"{j+1}:{lines_list[j]}" for j in range(start, end))
                results.append(f"{f}:{i+1}:\n{block}\n")

    if output_mode == "count":
        return f"匹配文件数: {len(matched_files)}"
    if output_mode == "files_with_matches":
        return "\n".join(results) if results else "(无匹配)"

    if len(results) > head_limit:
        results = results[:head_limit] + [f"...[共 {len(results)} 条匹配，仅显示前 {head_limit} 条]..."]
    return "\n".join(results) if results else "(无匹配)"


def get_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "grep",
            "description": "基于 ripgrep 的内容搜索工具。支持正则表达式、文件类型过滤、上下文行数、大小写不敏感等。用于在项目中搜索代码、日志、配置等内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "搜索模式（正则表达式）"},
                    "path": {"type": "string", "description": "搜索路径，可以是文件或目录", "default": "."},
                    "glob": {"type": "string", "description": "文件名过滤，如 '*.py' 或 '*.{ts,tsx}'"},
                    "type": {"type": "string", "description": "文件类型过滤，如 'py', 'js', 'rs'"},
                    "before": {"type": "integer", "description": "每个匹配前显示的上下文行数"},
                    "after": {"type": "integer", "description": "每个匹配后显示的上下文行数"},
                    "context": {"type": "integer", "description": "每个匹配前后显示的上下文行数"},
                    "ignore_case": {"type": "boolean", "description": "是否忽略大小写", "default": False},
                    "head_limit": {"type": "integer", "description": "最多返回的匹配数", "default": 50},
                    "multiline": {"type": "boolean", "description": "多行匹配模式", "default": False},
                    "output_mode": {"type": "string", "description": "输出模式：content(匹配内容)、files_with_matches(匹配文件)、count(计数)", "enum": ["content", "files_with_matches", "count"]},
                },
                "required": ["pattern"]
            }
        }
    }
