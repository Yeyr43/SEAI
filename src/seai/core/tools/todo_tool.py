"""
todo_tool — 任务列表管理工具

支持创建、读取、更新任务列表。每个任务包含状态和描述。
"""
import json
from pathlib import Path
from typing import Dict, Any


async def execute(args: Dict[str, Any]) -> str:
    items = args.get("items", [])
    if not items:
        return "错误: 未提供任务项 (items)"

    if not isinstance(items, list):
        return "错误: items 必须是数组"

    lines = ["## 任务列表", ""]
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            return f"错误: items[{i - 1}] 必须是对象"
        status = item.get("status", "pending")
        content = item.get("content", item.get("description", f"任务 {i}"))
        icon = {"pending": "☐", "in_progress": "◉", "completed": "✓"}.get(status, "☐")
        lines.append(f"{icon} **{content}**")
        if item.get("notes"):
            lines.append(f"  > {item['notes']}")

    summary_parts = []
    pending = sum(1 for it in items if it.get("status") == "pending")
    in_progress = sum(1 for it in items if it.get("status") == "in_progress")
    completed = sum(1 for it in items if it.get("status") == "completed")
    if pending:
        summary_parts.append(f"{pending} 个待办")
    if in_progress:
        summary_parts.append(f"{in_progress} 个进行中")
    if completed:
        summary_parts.append(f"{completed} 个已完成")

    lines.append("")
    lines.append(f"总计 {len(items)} 个任务: {', '.join(summary_parts) if summary_parts else '全部待办'}")
    return "\n".join(lines)


def get_definition() -> dict:
    return {
        "type": "function",
        "function": {
            "name": "todo",
            "description": "创建和管理任务列表。每个任务包含状态（pending/in_progress/completed）、描述和可选备注。用于跟踪多步骤任务的进度。",
            "parameters": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "任务项列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "status": {"type": "string", "enum": ["pending", "in_progress", "completed"], "description": "任务状态"},
                                "content": {"type": "string", "description": "任务描述"},
                                "notes": {"type": "string", "description": "可选的备注信息"},
                            },
                            "required": ["status", "content"]
                        }
                    }
                },
                "required": ["items"]
            }
        }
    }
