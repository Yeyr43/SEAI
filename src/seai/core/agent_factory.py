"""
SEAI Agent 工厂 — 从角色配置生成特定 Agent 实例

基于 SEAgent 基类 + 角色定义，生成具有特定能力、权限和提示词的 Agent。
扩展 SEAI 现有的 AgentPool，支持 SEAT 所需的所有角色类型。
角色定义在 core/role_definitions.py 中独立维护。
"""
from typing import List, Dict, Any
from loguru import logger
from .role_definitions import AgentRole, RoleDefinition, ROLE_DEFINITIONS


class AgentFactory:
    """Agent 工厂 — 从角色定义生成 Agent 实例"""

    def __init__(self, agent_class=None, llm_manager=None, tool_executor=None,
                 memory_store=None, permission_manager=None, skill_system=None):
        self._agent_class = agent_class  # SEAgent 类
        self._llm_manager = llm_manager
        self._tool_executor = tool_executor
        self._memory_store = memory_store
        self._permission_manager = permission_manager
        self._skill_system = skill_system
        self._created_agents: Dict[str, list] = {}  # role -> agent_ids

    def get_role_definition(self, role: AgentRole) -> RoleDefinition:
        """获取角色定义"""
        return ROLE_DEFINITIONS.get(role)

    def list_roles(self) -> List[dict]:
        """列出所有可用角色"""
        return [rd.to_dict() for rd in ROLE_DEFINITIONS.values()]

    def get_roles_for_capability(self, capability: str) -> List[AgentRole]:
        """根据能力标签查找匹配的角色"""
        matches = []
        for role, rd in ROLE_DEFINITIONS.items():
            if any(cap in c for c in rd.capabilities for cap in (capability, capability.lower())):
                matches.append(role)
        return matches

    def create_agent(self, role: AgentRole, agent_id: str = None,
                     config: Any = None, **overrides) -> Any:
        """从角色定义创建一个 Agent 实例"""
        import uuid
        rd = self.get_role_definition(role)
        if not rd:
            raise ValueError(f"未知角色: {role}")

        agent_id = agent_id or f"{role.value}_{uuid.uuid4().hex[:8]}"

        if self._agent_class is None:
            logger.warning("未设置 Agent 类，返回 None")
            return None

        agent = self._agent_class(config=config)

        # 注入角色信息
        agent.role = rd.role.value
        agent.role_definition = rd

        # 注册 LLM 层级
        if self._llm_manager and hasattr(self._llm_manager, 'register_agent'):
            from .llm_manager import ModelTier
            tier_map = {"light": ModelTier.LIGHT, "standard": ModelTier.STANDARD,
                       "enhanced": ModelTier.ENHANCED, "premium": ModelTier.PREMIUM}
            self._llm_manager.register_agent(agent_id, tier_map.get(rd.model_tier, ModelTier.STANDARD))

        # 注册权限
        if self._permission_manager and hasattr(self._permission_manager, 'register_agent'):
            self._permission_manager.register_agent(agent_id, rd.role.value)

        self._created_agents.setdefault(rd.role.value, []).append(agent_id)

        # 应用覆盖配置
        for key, value in overrides.items():
            if hasattr(agent, key):
                setattr(agent, key, value)

        logger.info(f"Agent 已创建: {agent_id} (role={rd.display_name})")
        return agent

    def create_team(self, roles: List[AgentRole], prefix: str = "") -> Dict[str, Any]:
        """批量创建一组 Agent"""
        team = {}
        for role in roles:
            agent_id = f"{prefix}{role.value}" if prefix else None
            try:
                team[role.value] = self.create_agent(role, agent_id=agent_id)
            except Exception as e:
                logger.error(f"创建 Agent [{role.value}] 失败: {e}")
                team[role.value] = None
        return team

    def get_created_agents(self, role: str = None) -> list:
        if role:
            return self._created_agents.get(role, [])
        return [aid for aids in self._created_agents.values() for aid in aids]

    def get_stats(self) -> dict:
        return {
            "total_agents": sum(len(v) for v in self._created_agents.values()),
            "by_role": {k: len(v) for k, v in self._created_agents.items()},
        }


agent_factory = AgentFactory()
