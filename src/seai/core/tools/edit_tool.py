"""
edit_tool — 基于精确字符串替换的文件编辑工具 (Rust 原子写入)

两层回退: Rust FileOps.edit_file → Pure Python
"""
from pathlib import Path
from typing import Dict, Any


async def execute(args: Dict[str, Any]) -> str:
    file_path = args.get("file_path", "")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    replace_all = args.get("replace_all", False)

    if not file_path:
        return "错误: 未提供文件路径 (file_path)"
    if not old_string and not replace_all:
        return "错误: 未提供要替换的字符串 (old_string)"

    # L1: Rust atomic edit
    try:
        from .._rust import is_rust_available, get_file_ops
        if is_rust_available():
            result = get_file_ops().edit_file(file_path, old_string, new_string, replace_all)
            if not result.startswith("[edit] 读取失败"):
                return result
    except Exception:
        pass

    # L2: Pure Python
    p = Path(file_path).resolve()
    if not p.exists():
        return f"文件不存在: {file_path}"
    if not p.is_file():
        return f"路径不是文件: {file_path}"

    try:
        content = p.read_text("utf-8", errors="replace")
    except Exception as e:
        return f"读取文件失败: {str(e)}"

    if replace_all:
        count = content.count(old_string)
        if count == 0:
            return f"未找到匹配的字符串: {old_string[:100]}..."
        new_content = content.replace(old_string, new_string)
        try:
            p.write_text(new_content, "utf-8")
            return f"全局替换成功，共替换 {count} 处"
        except Exception as e:
            return f"写入文件失败: {str(e)}"

    count = content.count(old_string)
    if count == 0:
        return f"未找到匹配的字符串。请确认 old_string 完全匹配文件内容（包括缩进和空白字符）。\n尝试匹配: {old_string[:200]}"
    if count > 1:
        lines_found = []
        for i, line in enumerate(content.split("\n"), 1):
            if old_string in line:
                lines_found.append(f"  第 {i} 行")
                if len(lines_found) >= 5:
                    break
        return (
            f"old_string 在文件中匹配了 {count} 次（必须唯一匹配）。\n"
            f"匹配位置:\n" + "\n".join(lines_found) + "\n"
            f"请提供更多上下文使匹配唯一，或使用 replace_all=true 进行全局替换。"
        )

    new_content = content.replace(old_string, new_string, 1)
    try:
        p.write_text(new_content, "utf-8")
        old_lines = old_string.count("\n") + 1
        new_lines = new_string.count("\n") + 1
        return f"编辑成功。替换了 {old_lines} 行为 {new_lines} 行。"
    except Exception as e:
        return f"写入文件失败: {str(e)}"


def get_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "edit",
            "description": "基于精确字符串替换的文件编辑工具。在文件中查找唯一匹配的 old_string 并替换为 new_string。要求匹配唯一，除非指定 replace_all=true 进行全局替换。保留原始缩进和格式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "要编辑的文件绝对路径"},
                    "old_string": {"type": "string", "description": "要替换的原字符串（必须精确匹配，包括缩进）"},
                    "new_string": {"type": "string", "description": "替换后的新字符串"},
                    "replace_all": {"type": "boolean", "description": "是否替换所有匹配项", "default": False},
                },
                "required": ["file_path", "old_string", "new_string"]
            }
        }
    }
