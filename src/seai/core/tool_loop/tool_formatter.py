"""工具格式化 — 文本模式工具提示构建 + 解析"""
import json
import re as _re
from typing import List, Dict


def build_text_tool_prompt(tools: List[Dict]) -> str:
    """将工具定义转换为 Markdown 文本，供不支持 function calling 的 API 使用"""
    lines = ["## 可用工具（必须使用以下格式调用）\n"]
    lines.append("要执行操作，请输出以下格式的代码块（每块只调用一个工具）：\n")
    lines.append("```tool_call")
    lines.append('{"name": "工具名", "arguments": {"参数名": "值"}}')
    lines.append("```\n")
    lines.append("可用工具列表：\n")
    for tool in tools:
        func = tool.get("function", tool)
        name = func.get("name", "")
        desc = func.get("description", "")
        params = func.get("parameters", {})
        props = params.get("properties", {})
        required = params.get("required", [])
        lines.append(f"- **{name}**: {desc}")
        if props:
            for pname, pinfo in props.items():
                req_mark = " [必填]" if pname in required else ""
                ptype = pinfo.get("type", "string")
                pdesc = pinfo.get("description", "")
                lines.append(f"  - `{pname}` ({ptype}){req_mark}: {pdesc}")
        lines.append("")
    lines.append("重要提示：不要只描述你打算做什么。必须输出 ```tool_call``` 代码块来实际执行操作。")
    return "\n".join(lines)


def parse_text_tool_calls(text: str) -> List[Dict]:
    """从文本中解析 tool_call 代码块"""
    pattern = _re.compile(r'```tool_call\s*\n(.*?)```', _re.DOTALL | _re.IGNORECASE)
    matches = pattern.findall(text)
    tool_calls = []
    for match in matches:
        try:
            data = json.loads(match.strip())
            if isinstance(data, dict) and "name" in data:
                tool_calls.append({
                    "id": f"text_{len(tool_calls)}",
                    "type": "function",
                    "function": {
                        "name": data["name"],
                        "arguments": json.dumps(data.get("arguments", {}), ensure_ascii=False)
                    }
                })
        except json.JSONDecodeError:
            pass
    return tool_calls


def normalize_messages(messages: List[Dict]) -> List[Dict]:
    """移除 tool 相关原生 function calling 字段，确保 API 兼容性"""
    cleaned = []
    for msg in messages:
        m = dict(msg)
        role = m.get("role", "")
        if role == "tool":
            tool_name = m.pop("tool_call_id", "unknown")
            content = m.get("content", "")
            m = {"role": "user", "content": f"[工具 {tool_name} 返回]\n{content}"}
        elif role == "assistant" and "tool_calls" in m:
            del m["tool_calls"]
        m.pop("tool_call_id", None)
        cleaned.append(m)
    return cleaned
