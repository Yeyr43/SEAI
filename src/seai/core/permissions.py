"""
SEAI 权限控制框架 — 基于角色和任务阶段的工具权限管理

支持：
- 按 Agent 角色授予/拒绝工具
- 按任务阶段动态调整权限（规划阶段只读，执行阶段全权限）
- Bash 命令白名单/黑名单正则匹配
- 预定义权限模板
"""
from dataclasses import dataclass, field
from typing import List, Set, Optional
from enum import Enum


class ExecutionPhase(str, Enum):
    PLAN = "plan"           # 规划模式 — 仅允许只读工具
    EXECUTE = "execute"     # 执行模式 — 允许所有授权工具
    REVIEW = "review"       # 审查模式 — 允许只读 + 检查工具
    RESTRICTED = "restricted"  # 受限模式 — 最小权限集


@dataclass
class Permission:
    """单个 Agent 或角色的权限定义"""
    allow_tools: Set[str] = field(default_factory=set)
    deny_tools: Set[str] = field(default_factory=set)
    allow_bash_patterns: List[str] = field(default_factory=list)
    deny_bash_patterns: List[str] = field(default_factory=list)

    def check_tool(self, tool_name: str) -> bool:
        """检查工具是否被允许"""
        if tool_name in self.deny_tools:
            return False
        if "*" in self.allow_tools or "all" in self.allow_tools:
            return True
        if tool_name in self.allow_tools:
            return True
        return len(self.allow_tools) == 0  # 空 allow 表示允许所有

    def check_bash_command(self, command: str) -> bool:
        """检查 bash 命令是否被允许"""
        import re
        for pattern in self.deny_bash_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return False
        if not self.allow_bash_patterns:
            return True
        for pattern in self.allow_bash_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return True
        return False


# 预定义权限模板
PLAN_MODE = Permission(
    allow_tools={"read_file", "list_files", "grep", "glob", "web_search", "echo", "calculator"},
    deny_tools={"write_file", "delete_file", "edit", "bash", "execute_command", "execute_python"},
    allow_bash_patterns=[],
    deny_bash_patterns=[".*"],
)

EXECUTION_MODE = Permission(
    allow_tools={"*"},
    deny_tools=set(),
    allow_bash_patterns=[],
    deny_bash_patterns=[],
)

RESTRICTED_MODE = Permission(
    allow_tools={"read_file", "list_files", "grep", "glob", "echo", "calculator"},
    deny_tools={"write_file", "delete_file", "edit", "bash", "execute_command", "execute_python",
                "web_search", "fetch_url", "encode_image", "encode_audio"},
    allow_bash_patterns=[],
    deny_bash_patterns=[".*"],
)

# 角色默认权限
ROLE_PERMISSIONS = {
    "commander": PLAN_MODE,
    "inspector": PLAN_MODE,
    "executor": EXECUTION_MODE,
    "engineer": Permission(
        allow_tools={"*"},
        deny_tools={"execute_command", "delete_file"},
    ),
    "researcher": Permission(
        allow_tools={"read_file", "list_files", "grep", "glob", "web_search", "fetch_url", "echo", "calculator"},
        deny_tools={"write_file", "delete_file", "edit", "bash", "execute_command", "execute_python"},
    ),
    "analyst": Permission(
        allow_tools={"read_file", "list_files", "grep", "glob", "web_search", "fetch_url", "echo", "calculator", "execute_python"},
        deny_tools={"write_file", "delete_file", "edit", "bash", "execute_command"},
    ),
    "safety_guard": RESTRICTED_MODE,
    "toolsmith": EXECUTION_MODE,
    "code_analyzer": PLAN_MODE,
    "test_writer": Permission(
        allow_tools={"*"},
        deny_tools={"delete_file"},
    ),
    "code_reviewer": PLAN_MODE,
    "critic": PLAN_MODE,
    "communicator": RESTRICTED_MODE,
    "memo_writer": Permission(
        allow_tools={"read_file", "write_file", "list_files", "echo", "calculator"},
        deny_tools={"delete_file", "bash", "execute_command", "execute_python"},
    ),
    "meta_monitor": RESTRICTED_MODE,
    "planner": PLAN_MODE,
}


class PermissionManager:
    """权限管理器 — 根据 Agent 角色和任务阶段返回权限集"""

    def __init__(self):
        self._agent_permissions: dict = {}
        self._phase_overrides: dict = {}  # agent_id -> ExecutionPhase

    def register_agent(self, agent_id: str, role: str = "executor"):
        """注册 Agent 的默认权限"""
        perm = ROLE_PERMISSIONS.get(role, EXECUTION_MODE)
        self._agent_permissions[agent_id] = perm

    def unregister_agent(self, agent_id: str):
        self._agent_permissions.pop(agent_id, None)
        self._phase_overrides.pop(agent_id, None)

    def set_phase(self, agent_id: str, phase: ExecutionPhase):
        """为 Agent 设置当前执行阶段"""
        self._phase_overrides[agent_id] = phase

    def get_permission(self, agent_id: str = None) -> Permission:
        """获取 Agent 当前权限"""
        if agent_id and agent_id in self._phase_overrides:
            phase = self._phase_overrides[agent_id]
            return _phase_permission(phase)
        if agent_id and agent_id in self._agent_permissions:
            return self._agent_permissions[agent_id]
        return EXECUTION_MODE

    def check_tool(self, agent_id: str, tool_name: str) -> bool:
        return self.get_permission(agent_id).check_tool(tool_name)

    def check_bash(self, agent_id: str, command: str) -> bool:
        return self.get_permission(agent_id).check_bash_command(command)


def _phase_permission(phase: ExecutionPhase) -> Permission:
    if phase == ExecutionPhase.PLAN:
        return PLAN_MODE
    if phase == ExecutionPhase.REVIEW:
        return PLAN_MODE
    if phase == ExecutionPhase.RESTRICTED:
        return RESTRICTED_MODE
    return EXECUTION_MODE


permission_manager = PermissionManager()
