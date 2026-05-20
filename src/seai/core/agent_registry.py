"""
SEAI Agent 注册中心 - 动态 Agent 角色注册与发现
支持自定义 Agent 角色、能力声明、生命周期管理
"""
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger


class AgentCapability(str, Enum):
    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    WEB_SEARCH = "web_search"
    URL_FETCH = "url_fetch"
    SKILL_EXECUTION = "skill_execution"
    MEMORY_ACCESS = "memory_access"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    CONSTRAINT_CHECK = "constraint_check"
    EVOLUTION = "evolution"
    TESTING = "testing"


@dataclass
class AgentRoleDefinition:
    name: str
    description: str = ""
    capabilities: List[AgentCapability] = field(default_factory=list)
    system_prompt: str = ""
    max_tokens: int = 3000
    priority: int = 0
    enabled: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "capabilities": [c.value for c in self.capabilities],
            "max_tokens": self.max_tokens,
            "priority": self.priority,
            "enabled": self.enabled,
            "metadata": self.metadata,
        }


class AgentRegistry:
    """Agent 注册中心 - 管理 Agent 角色定义和工厂"""

    def __init__(self):
        self._roles: Dict[str, AgentRoleDefinition] = {}
        self._factories: Dict[str, Callable] = {}
        self._instances: Dict[str, Any] = {}
        self._register_builtin_roles()

    def _register_builtin_roles(self):
        builtin = [
            AgentRoleDefinition(
                name="orchestrator",
                description="任务编排与路由",
                capabilities=[
                    AgentCapability.CONSTRAINT_CHECK,
                    AgentCapability.MEMORY_ACCESS,
                ],
                system_prompt="你是任务编排器，负责分析用户请求并分派给合适的 Agent。",
                priority=10,
            ),
            AgentRoleDefinition(
                name="explorer",
                description="代码探索与搜索",
                capabilities=[
                    AgentCapability.FILE_READ,
                    AgentCapability.WEB_SEARCH,
                    AgentCapability.URL_FETCH,
                    AgentCapability.KNOWLEDGE_GRAPH,
                ],
                system_prompt="你是代码探索器，负责搜索代码库、查找文件和获取信息。",
                priority=5,
            ),
            AgentRoleDefinition(
                name="coder",
                description="代码生成与修改",
                capabilities=[
                    AgentCapability.FILE_READ,
                    AgentCapability.FILE_WRITE,
                    AgentCapability.CODE_GENERATION,
                ],
                system_prompt="你是代码生成器，负责编写和修改代码文件。",
                priority=5,
            ),
            AgentRoleDefinition(
                name="reviewer",
                description="代码审查与质量检查",
                capabilities=[
                    AgentCapability.FILE_READ,
                    AgentCapability.CODE_REVIEW,
                    AgentCapability.TESTING,
                ],
                system_prompt="你是代码审查器，负责检查代码质量和发现潜在问题。",
                priority=3,
            ),
            AgentRoleDefinition(
                name="test_runner",
                description="测试执行与验证",
                capabilities=[
                    AgentCapability.FILE_READ,
                    AgentCapability.SKILL_EXECUTION,
                    AgentCapability.TESTING,
                ],
                system_prompt="你是测试执行器，负责运行测试并验证结果。",
                priority=3,
            ),
        ]
        for role in builtin:
            self.register_role(role)

    def register_role(self, role: AgentRoleDefinition):
        self._roles[role.name] = role
        logger.info(f"注册 Agent 角色: {role.name} (capabilities={[c.value for c in role.capabilities]})")

    def unregister_role(self, name: str):
        self._roles.pop(name, None)
        self._factories.pop(name, None)
        self._instances.pop(name, None)

    def register_factory(self, role_name: str, factory: Callable):
        if role_name not in self._roles:
            logger.warning(f"注册工厂时角色不存在: {role_name}")
        self._factories[role_name] = factory

    def get_role(self, name: str) -> Optional[AgentRoleDefinition]:
        return self._roles.get(name)

    def list_roles(self) -> List[AgentRoleDefinition]:
        return list(self._roles.values())

    def find_roles_by_capability(self, capability: AgentCapability) -> List[AgentRoleDefinition]:
        return [r for r in self._roles.values() if capability in r.capabilities]

    def create_agent(self, role_name: str, **kwargs) -> Optional[Any]:
        role = self._roles.get(role_name)
        if not role or not role.enabled:
            return None

        factory = self._factories.get(role_name)
        if factory:
            instance = factory(role, **kwargs)
            self._instances[role_name] = instance
            return instance

        return None

    def get_instance(self, role_name: str) -> Optional[Any]:
        return self._instances.get(role_name)

    def get_stats(self) -> dict:
        return {
            "total_roles": len(self._roles),
            "enabled_roles": sum(1 for r in self._roles.values() if r.enabled),
            "registered_factories": len(self._factories),
            "active_instances": len(self._instances),
            "roles": [r.to_dict() for r in self._roles.values()],
        }


agent_registry = AgentRegistry()