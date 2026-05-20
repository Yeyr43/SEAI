"""
SEAT Agent 角色定义 — 16 个预设角色的完整配置

从 agent_factory.py 提取的静态数据，便于独立维护和配置。
"""
from dataclasses import dataclass, field
from typing import List
from enum import Enum


class AgentRole(str, Enum):
    """SEAT 标准 Agent 角色"""
    COMMANDER = "commander"
    INSPECTOR = "inspector"
    EXECUTOR = "executor"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    PLANNER = "planner"
    ENGINEER = "engineer"
    TOOLSMITH = "toolsmith"
    CRITIC = "critic"
    SAFETY_GUARD = "safety_guard"
    COMMUNICATOR = "communicator"
    MEMO_WRITER = "memo_writer"
    META_MONITOR = "meta_monitor"
    CODE_ANALYZER = "code_analyzer"
    TEST_WRITER = "test_writer"
    CODE_REVIEWER = "code_reviewer"


@dataclass
class RoleDefinition:
    """角色定义 — 描述一个 Agent 角色的完整配置"""
    role: AgentRole
    display_name: str
    description: str
    capabilities: List[str] = field(default_factory=list)
    allowed_tools: List[str] = field(default_factory=list)
    denied_tools: List[str] = field(default_factory=list)
    model_tier: str = "standard"
    system_prompt_suffix: str = ""
    skill_preferences: List[str] = field(default_factory=list)
    max_parallel_tasks: int = 1

    def to_dict(self) -> dict:
        return {
            "role": self.role.value,
            "display_name": self.display_name,
            "description": self.description,
            "capabilities": self.capabilities,
            "allowed_tools": self.allowed_tools,
            "model_tier": self.model_tier,
            "max_parallel_tasks": self.max_parallel_tasks,
        }


ROLE_DEFINITIONS = {
    AgentRole.COMMANDER: RoleDefinition(
        role=AgentRole.COMMANDER,
        display_name="Commander（指挥官）",
        description="任务接收、TDE 评估、TaskCard 发放、子 Agent 调度。不直接执行工具操作。",
        capabilities=["task_decomposition", "resource_allocation", "priority_management"],
        allowed_tools=["read_file", "grep", "glob", "web_search", "todo"],
        denied_tools=["write_file", "delete_file", "edit", "bash", "execute_command"],
        model_tier="premium",
        system_prompt_suffix=(
            "你是 SEAT 的 Commander，负责任务分析和分配。"
            "收到任务后，评估复杂度，分解为子任务，分配给合适的 Agent 角色。"
            "你不需要直接执行操作，而是协调团队完成。"
        ),
        max_parallel_tasks=5,
    ),

    AgentRole.INSPECTOR: RoleDefinition(
        role=AgentRole.INSPECTOR,
        display_name="Inspector（检查官）",
        description="监听 Agent 心跳，维护任务状态机，检测死锁，触发状态转换。",
        capabilities=["heartbeat_monitoring", "deadlock_detection", "quality_assessment"],
        allowed_tools=["read_file", "grep", "glob", "todo"],
        denied_tools=["write_file", "delete_file", "edit", "bash", "execute_command"],
        model_tier="premium",
        system_prompt_suffix=(
            "你是 SEAT 的 Inspector，负责监控任务执行质量。"
            "定期检查各 Agent 的心跳和进展，发现偏离计划或死锁时及时报告。"
        ),
        max_parallel_tasks=10,
    ),

    AgentRole.EXECUTOR: RoleDefinition(
        role=AgentRole.EXECUTOR,
        display_name="Executor（执行者）",
        description="执行具体任务：工具调用、文件操作、命令执行。",
        capabilities=["tool_execution", "file_operations", "command_execution"],
        allowed_tools=["*"],
        denied_tools=[],
        model_tier="standard",
        system_prompt_suffix=(
            "你是 SEAT 的 Executor，负责具体执行任务。你拥有完整的工具权限，"
            "可以读写文件、执行命令、搜索代码。执行完成后汇报结果。"
        ),
        max_parallel_tasks=3,
    ),

    AgentRole.RESEARCHER: RoleDefinition(
        role=AgentRole.RESEARCHER,
        display_name="Researcher（研究员）",
        description="信息收集、代码搜索、文档查阅。仅做研究，不修改文件。",
        capabilities=["code_search", "web_research", "documentation_lookup"],
        allowed_tools=["read_file", "list_files", "grep", "glob", "web_search", "fetch_url", "echo", "calculator"],
        denied_tools=["write_file", "delete_file", "edit", "bash", "execute_command", "execute_python"],
        model_tier="standard",
        system_prompt_suffix="你是 SEAT 的 Researcher，负责信息收集和研究。你只读不写。",
    ),

    AgentRole.ANALYST: RoleDefinition(
        role=AgentRole.ANALYST,
        display_name="Analyst（分析师）",
        description="数据分析、代码审查、性能分析。",
        capabilities=["data_analysis", "code_review", "performance_analysis"],
        allowed_tools=["read_file", "grep", "glob", "execute_python", "web_search", "echo", "calculator"],
        denied_tools=["write_file", "delete_file", "edit", "bash", "execute_command"],
        model_tier="standard",
    ),

    AgentRole.PLANNER: RoleDefinition(
        role=AgentRole.PLANNER,
        display_name="Planner（规划师）",
        description="复杂任务规划、步骤分解、依赖分析。",
        capabilities=["task_planning", "dependency_analysis", "risk_assessment"],
        allowed_tools=["read_file", "grep", "glob", "web_search", "todo"],
        denied_tools=["write_file", "delete_file", "edit", "bash", "execute_command"],
        model_tier="enhanced",
    ),

    AgentRole.ENGINEER: RoleDefinition(
        role=AgentRole.ENGINEER,
        display_name="Engineer（工程师）",
        description="代码编写、重构、功能实现。",
        capabilities=["code_generation", "refactoring", "feature_implementation"],
        allowed_tools=["*"],
        denied_tools=["execute_command"],
        model_tier="enhanced",
    ),

    AgentRole.TOOLSMITH: RoleDefinition(
        role=AgentRole.TOOLSMITH,
        display_name="Toolsmith（工具匠）",
        description="工具创建、技能开发、沙箱扩展。",
        capabilities=["tool_creation", "skill_development", "sandbox_extension"],
        allowed_tools=["*"],
        denied_tools=[],
        model_tier="standard",
    ),

    AgentRole.CRITIC: RoleDefinition(
        role=AgentRole.CRITIC,
        display_name="Critic（评论家）",
        description="代码审查、质量评估、改进建议。",
        capabilities=["code_review", "quality_audit", "improvement_suggestion"],
        allowed_tools=["read_file", "grep", "glob", "web_search", "todo"],
        denied_tools=["write_file", "delete_file", "edit", "bash", "execute_command"],
        model_tier="standard",
    ),

    AgentRole.SAFETY_GUARD: RoleDefinition(
        role=AgentRole.SAFETY_GUARD,
        display_name="Safety Guard（安全卫士）",
        description="安全审查、权限检查、危险操作拦截。",
        capabilities=["security_audit", "permission_check", "danger_detection"],
        allowed_tools=["read_file", "grep", "glob"],
        denied_tools=["write_file", "delete_file", "edit", "bash", "execute_command",
                      "execute_python", "web_search", "fetch_url"],
        model_tier="standard",
    ),

    AgentRole.COMMUNICATOR: RoleDefinition(
        role=AgentRole.COMMUNICATOR,
        display_name="Communicator（通信员）",
        description="消息路由、结果汇总、对外接口。",
        capabilities=["message_routing", "result_aggregation", "external_interface"],
        allowed_tools=["read_file", "echo", "todo"],
        denied_tools=["write_file", "delete_file", "edit", "bash", "execute_command",
                      "execute_python", "web_search"],
        model_tier="light",
    ),

    AgentRole.MEMO_WRITER: RoleDefinition(
        role=AgentRole.MEMO_WRITER,
        display_name="Memo Writer（记录员）",
        description="记忆写入、日志记录、知识库维护。",
        capabilities=["memory_writing", "logging", "knowledge_base_maintenance"],
        allowed_tools=["read_file", "write_file", "list_files", "echo", "todo"],
        denied_tools=["delete_file", "bash", "execute_command", "execute_python"],
        model_tier="light",
    ),

    AgentRole.META_MONITOR: RoleDefinition(
        role=AgentRole.META_MONITOR,
        display_name="Meta Monitor（元监控）",
        description="系统健康监控、资源使用追踪、性能告警。",
        capabilities=["health_monitoring", "resource_tracking", "performance_alert"],
        allowed_tools=["read_file", "echo", "todo"],
        denied_tools=["write_file", "delete_file", "edit", "bash", "execute_command",
                      "execute_python", "web_search", "fetch_url"],
        model_tier="light",
    ),

    AgentRole.CODE_ANALYZER: RoleDefinition(
        role=AgentRole.CODE_ANALYZER,
        display_name="Code Analyzer（代码分析器）",
        description="静态代码分析、AST 解析、代码图谱查询。",
        capabilities=["static_analysis", "ast_parsing", "code_graph_query"],
        allowed_tools=["read_file", "grep", "glob", "execute_python", "todo"],
        denied_tools=["write_file", "delete_file", "edit", "bash", "execute_command"],
        model_tier="enhanced",
    ),

    AgentRole.TEST_WRITER: RoleDefinition(
        role=AgentRole.TEST_WRITER,
        display_name="Test Writer（测试编写者）",
        description="单元测试生成、集成测试编写、测试覆盖率提升。",
        capabilities=["test_generation", "coverage_improvement", "test_automation"],
        allowed_tools=["*"],
        denied_tools=["delete_file"],
        model_tier="enhanced",
    ),

    AgentRole.CODE_REVIEWER: RoleDefinition(
        role=AgentRole.CODE_REVIEWER,
        display_name="Code Reviewer（代码审查者）",
        description="代码审查、最佳实践检查、安全漏洞检测。",
        capabilities=["code_review", "best_practice_check", "vulnerability_detection"],
        allowed_tools=["read_file", "grep", "glob", "execute_python", "todo"],
        denied_tools=["write_file", "delete_file", "edit", "bash", "execute_command"],
        model_tier="enhanced",
    ),
}
