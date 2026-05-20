"""
ConfigManager 单元测试
"""
import pytest
import json
from pathlib import Path
from seai.core.config import ConfigManager, LLMEndpointConfig, SecurityConfig, SystemConfig


class TestLLMEndpointConfig:
    """LLM端点配置单元测试"""

    def test_creation(self):
        ep = LLMEndpointConfig(
            name="test", api_base="http://localhost:8000",
            api_key="sk-test", model="gpt-4"
        )
        assert ep.name == "test"
        assert ep.api_base == "http://localhost:8000"
        assert ep.api_key == "sk-test"
        assert ep.model == "gpt-4"

    def test_default_values(self):
        ep = LLMEndpointConfig(
            name="minimal", api_base="http://localhost:8000",
            api_key="sk-test", model="gpt-4"
        )
        assert ep.priority == 0


class TestSecurityConfig:
    """安全配置单元测试"""

    def test_default_values(self):
        sc = SecurityConfig(command_whitelist=[], write_whitelist=[])
        assert sc.enable_sandbox is True
        assert sc.max_file_size > 0
        assert isinstance(sc.command_whitelist, list)
        assert isinstance(sc.write_whitelist, list)

    def test_custom_values(self):
        sc = SecurityConfig(
            command_whitelist=["ls", "cat"],
            write_whitelist=["/tmp"],
            enable_sandbox=False,
            max_file_size=5000
        )
        assert sc.enable_sandbox is False
        assert sc.max_file_size == 5000
        assert "ls" in sc.command_whitelist
        assert "/tmp" in sc.write_whitelist


class TestSystemConfig:
    """系统配置单元测试"""

    def test_default_paths(self):
        sc = SystemConfig(
            base_dir=Path("/test"),
            data_dir=Path("/test/data"),
            workspace_dir=Path("/test/data/workspace"),
            logs_dir=Path("/test/data/logs")
        )
        assert sc.base_dir == Path("/test")
        assert sc.data_dir == Path("/test/data")
        assert sc.workspace_dir == Path("/test/data/workspace")
        assert sc.logs_dir == Path("/test/data/logs")

    def test_path_relationships(self):
        sc = SystemConfig(
            base_dir=Path("/test"),
            data_dir=Path("/test/data"),
            workspace_dir=Path("/test/data/workspace"),
            logs_dir=Path("/test/data/logs")
        )
        assert sc.workspace_dir.parent == sc.data_dir
        assert sc.logs_dir.parent == sc.data_dir


class TestConfigManager:
    """配置管理器单元测试"""

    def test_creation(self):
        cm = ConfigManager()
        assert cm is not None
        assert hasattr(cm, 'get')
        assert hasattr(cm, 'set')

    def test_get_set(self, tmp_path):
        config_path = tmp_path / "config.json"
        cm = ConfigManager(config_path)
        cm.set("test_key", "test_value")
        assert cm.get("test_key") == "test_value"

    def test_get_with_default(self, tmp_path):
        config_path = tmp_path / "config.json"
        cm = ConfigManager(config_path)
        assert cm.get("nonexistent", "default") == "default"

    def test_save_and_load(self, tmp_path):
        config_path = tmp_path / "config.json"
        cm1 = ConfigManager(config_path)
        cm1.set("persist_key", "persist_value")
        cm1.save_config()

        cm2 = ConfigManager(config_path)
        assert cm2.get("persist_key") == "persist_value"

    def test_get_llm_endpoints(self):
        cm = ConfigManager()
        endpoints = cm.get_llm_endpoints()
        assert isinstance(endpoints, list)

    def test_get_security_config(self):
        cm = ConfigManager()
        sc = cm.get_security_config()
        assert isinstance(sc, SecurityConfig)

    def test_get_memory_config(self):
        cm = ConfigManager()
        mc = cm.get_memory_config()
        assert mc.persist_dir is not None

    def test_get_system_config(self):
        cm = ConfigManager()
        sc = cm.get_system_config()
        assert isinstance(sc, SystemConfig)
        assert sc.base_dir is not None

    def test_update_llm_endpoints(self, tmp_path):
        config_path = tmp_path / "config.json"
        cm = ConfigManager(config_path)
        new_eps = [
            LLMEndpointConfig(
                name="updated", api_base="http://updated:8000",
                api_key="sk-updated", model="updated-model"
            )
        ]
        cm.update_llm_endpoints(new_eps)
        cm.save_config()

        cm2 = ConfigManager(config_path)
        eps = cm2.get_llm_endpoints()
        assert len(eps) == 1
        assert eps[0].name == "updated"

    def test_environment_override(self, monkeypatch, tmp_path):
        config_path = tmp_path / "config.json"
        cm = ConfigManager(config_path)
        cm.set("data_dir", "/config/path")
        cm.save_config()

        monkeypatch.setenv("SEAI_DATA_DIR", "/env/path")
        cm2 = ConfigManager(config_path)
        assert cm2.get("data_dir") == "/env/path"
