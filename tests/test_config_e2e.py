"""
配置管理系统端到端测试
"""
import pytest
from pathlib import Path
from seai.core.config import ConfigManager, LLMEndpointConfig, SecurityConfig


class TestConfigE2E:
    """配置管理系统端到端测试"""
    
    def test_config_manager_creation(self):
        """测试配置管理器创建"""
        config = ConfigManager()
        assert config is not None
        assert hasattr(config, 'get')
        assert hasattr(config, 'set')
        assert hasattr(config, 'save_config')
    
    def test_config_loading(self):
        """测试配置加载"""
        config = ConfigManager()
        
        # 测试基础配置获取
        llm_endpoints = config.get_llm_endpoints()
        assert isinstance(llm_endpoints, list)
        
        security_config = config.get_security_config()
        assert isinstance(security_config, SecurityConfig)
        
        memory_config = config.get_memory_config()
        assert memory_config.persist_dir.exists() or memory_config.persist_dir.parent.exists()
    
    def test_config_updates(self, tmp_path):
        """测试配置更新"""
        # 使用临时目录进行测试
        test_config_path = tmp_path / "test_config.json"
        config = ConfigManager(test_config_path)
        
        # 更新配置
        new_endpoints = [
            LLMEndpointConfig(
                name="test_endpoint",
                api_base="http://test:8000",
                api_key="test_key",
                model="test_model"
            )
        ]
        config.update_llm_endpoints(new_endpoints)
        
        # 保存配置
        config.save_config()
        
        # 验证配置已保存
        assert test_config_path.exists()
        
        # 重新加载验证
        new_config = ConfigManager(test_config_path)
        endpoints = new_config.get_llm_endpoints()
        assert len(endpoints) == 1
        assert endpoints[0].name == "test_endpoint"
    
    def test_environment_variables(self, monkeypatch):
        """测试环境变量优先级"""
        monkeypatch.setenv("SEAI_DATA_DIR", "/test/env/path")
        
        config = ConfigManager()
        data_dir = config.get("data_dir")
        
        # 环境变量应该优先于配置文件
        assert data_dir == "/test/env/path"
    
    def test_security_config_validation(self):
        """测试安全配置验证"""
        config = ConfigManager()
        security_config = config.get_security_config()
        
        # 检查默认配置
        assert len(security_config.command_whitelist) > 0
        assert security_config.enable_sandbox == True
        assert security_config.max_file_size > 0
    
    def test_system_config_paths(self):
        """测试系统配置路径"""
        config = ConfigManager()
        system_config = config.get_system_config()
        
        # 检查路径配置
        assert system_config.base_dir is not None
        assert system_config.data_dir is not None
        assert system_config.workspace_dir is not None
        assert system_config.logs_dir is not None
        
        # 检查路径关系
        assert system_config.workspace_dir.parent == system_config.data_dir
        assert system_config.logs_dir.parent == system_config.data_dir