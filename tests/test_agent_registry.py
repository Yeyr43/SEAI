"""
测试 SEAI Agent 注册中心
"""
import pytest
from seai.core.agent_registry import (
    AgentRegistry, AgentRoleDefinition, AgentCapability, agent_registry,
)


class TestAgentRoleDefinition:
    def test_creation(self):
        role = AgentRoleDefinition(
            name="test_role",
            description="A test role",
            capabilities=[AgentCapability.FILE_READ, AgentCapability.CODE_GENERATION],
            max_tokens=2000,
            priority=5,
        )
        assert role.name == "test_role"
        assert role.description == "A test role"
        assert len(role.capabilities) == 2
        assert role.max_tokens == 2000
        assert role.priority == 5
        assert role.enabled is True

    def test_to_dict(self):
        role = AgentRoleDefinition(
            name="test_role",
            capabilities=[AgentCapability.FILE_READ],
            metadata={"version": "1.0"},
        )
        d = role.to_dict()
        assert d["name"] == "test_role"
        assert "file_read" in d["capabilities"]
        assert d["metadata"]["version"] == "1.0"


class TestAgentRegistry:
    def setup_method(self):
        self.registry = AgentRegistry()

    def test_builtin_roles(self):
        roles = self.registry.list_roles()
        role_names = [r.name for r in roles]
        assert "orchestrator" in role_names
        assert "explorer" in role_names
        assert "coder" in role_names
        assert "reviewer" in role_names
        assert "test_runner" in role_names

    def test_register_custom_role(self):
        role = AgentRoleDefinition(
            name="custom",
            capabilities=[AgentCapability.FILE_READ],
        )
        self.registry.register_role(role)
        assert self.registry.get_role("custom") is not None

    def test_unregister_role(self):
        self.registry.unregister_role("explorer")
        assert self.registry.get_role("explorer") is None

    def test_find_by_capability(self):
        roles = self.registry.find_roles_by_capability(AgentCapability.CODE_GENERATION)
        role_names = [r.name for r in roles]
        assert "coder" in role_names

    def test_find_by_capability_none(self):
        roles = self.registry.find_roles_by_capability(AgentCapability.EVOLUTION)
        assert len(roles) == 0

    def test_register_factory(self):
        factory_called = []

        def factory(role, **kwargs):
            factory_called.append(role.name)
            return {"role": role.name}

        self.registry.register_factory("explorer", factory)
        instance = self.registry.create_agent("explorer")

        assert len(factory_called) == 1
        assert factory_called[0] == "explorer"
        assert instance == {"role": "explorer"}

    def test_create_agent_disabled_role(self):
        role = self.registry.get_role("explorer")
        role.enabled = False

        instance = self.registry.create_agent("explorer")
        assert instance is None

    def test_get_instance(self):
        def factory(role, **kwargs):
            return f"instance-{role.name}"

        self.registry.register_factory("explorer", factory)
        self.registry.create_agent("explorer")

        instance = self.registry.get_instance("explorer")
        assert instance == "instance-explorer"

    def test_get_stats(self):
        stats = self.registry.get_stats()
        assert stats["total_roles"] == 5
        assert stats["enabled_roles"] == 5
        assert len(stats["roles"]) == 5

    def test_global_registry(self):
        assert agent_registry is not None
        roles = agent_registry.list_roles()
        assert len(roles) >= 5