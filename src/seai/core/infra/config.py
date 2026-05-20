"""
统一配置管理模块
提供集中式的配置管理，支持环境变量、配置文件、默认值、敏感数据加密存储
"""
import os
import json
from pathlib import Path
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from .crypto import encrypt_sensitive_config, decrypt_sensitive_config, is_encrypted

_SENSITIVE_KEYS = ["api_key", "github_token"]


class LLMEndpointConfig(BaseModel):
    """LLM 端点配置"""
    name: str
    api_base: str
    api_key: str = "ollama"
    model: str = ""
    priority: int = 0


class SecurityConfig(BaseModel):
    """安全配置"""
    command_whitelist: List[str] = Field(default_factory=lambda: ["echo", "dir", "git", "python", "pip"])
    write_whitelist: List[str] = Field(default_factory=list)
    enable_sandbox: bool = True
    max_file_size: int = Field(default=1048576, ge=1024, le=1073741824)


class MemoryConfig(BaseModel):
    """记忆配置"""
    persist_dir: Path
    max_short_term_memories: int = Field(default=1000, ge=10)
    max_long_term_memories: int = Field(default=10000, ge=100)
    archive_after_days: int = Field(default=30, ge=1)
    max_media_size_mb: int = Field(default=50, ge=1, le=1024)


class SystemConfig(BaseModel):
    """系统配置"""
    base_dir: Path
    data_dir: Path
    workspace_dir: Path
    logs_dir: Path
    enable_hot_reload: bool = True
    enable_backup: bool = True
    backup_interval_hours: int = Field(default=24, ge=1)
    allowed_origins: List[str] = Field(default_factory=list)


class ConfigManager:
    """配置管理器"""
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or self._get_default_config_path()
        self._config_cache: Dict[str, Any] = {}
        self._load_config()
    
    def _get_default_config_path(self) -> Path:
        """获取默认配置文件路径"""
        project_se_data = Path(__file__).parent.parent.parent.parent.parent / "data"
        data_dir = Path(os.environ.get("SEAI_DATA", str(project_se_data)))
        return data_dir / "config.json"
    
    def _load_config(self):
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
            self._config_cache = decrypt_sensitive_config(raw, _SENSITIVE_KEYS)
        else:
            self._config_cache = {}
    
    def save_config(self):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        to_save = encrypt_sensitive_config(self._config_cache, _SENSITIVE_KEYS)
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(to_save, f, indent=2, ensure_ascii=False)
    
    def get(self, key: str, default: Any = None) -> Any:
        """获取配置值"""
        # 优先使用环境变量
        env_key = f"SEAI_{key.upper()}"
        if env_key in os.environ:
            return os.environ[env_key]
        
        # 然后使用配置文件
        return self._config_cache.get(key, default)
    
    def set(self, key: str, value: Any):
        """设置配置值"""
        self._config_cache[key] = value
    
    def get_llm_endpoints(self) -> List[LLMEndpointConfig]:
        """获取 LLM 端点配置"""
        endpoints_data = self.get("llm_endpoints", [])
        return [
            LLMEndpointConfig(
                name=ep.get("name", ""),
                api_base=ep.get("api_base", ""),
                api_key=ep.get("api_key", "ollama"),
                model=ep.get("model", ""),
                priority=ep.get("priority", 0)
            )
            for ep in endpoints_data
        ]
    
    def get_security_config(self) -> SecurityConfig:
        """获取安全配置"""
        security_data = self.get("security", {})
        return SecurityConfig(
            command_whitelist=security_data.get("command_whitelist", ["echo", "dir", "git", "python", "pip"]),
            write_whitelist=security_data.get("write_whitelist", []),
            enable_sandbox=security_data.get("enable_sandbox", True),
            max_file_size=security_data.get("max_file_size", 1024 * 1024)
        )
    
    def get_memory_config(self) -> MemoryConfig:
        """获取记忆配置"""
        data_dir = Path(self.get("data_dir", str(Path.cwd().parent / "data")))
        return MemoryConfig(
            persist_dir=data_dir / "memory",
            max_short_term_memories=self.get("max_short_term_memories", 1000),
            max_long_term_memories=self.get("max_long_term_memories", 10000),
            archive_after_days=self.get("archive_after_days", 30)
        )
    
    def get_system_config(self) -> SystemConfig:
        """获取系统配置"""
        base_dir = Path(self.get("base_dir", str(Path.cwd())))
        data_dir = Path(self.get("data_dir", str(Path.cwd().parent / "data")))
        return SystemConfig(
            base_dir=base_dir,
            data_dir=data_dir,
            workspace_dir=data_dir / "workspace",
            logs_dir=data_dir / "logs",
            enable_hot_reload=self.get("enable_hot_reload", True),
            enable_backup=self.get("enable_backup", True),
            backup_interval_hours=self.get("backup_interval_hours", 24)
        )
    
    def update_llm_endpoints(self, endpoints: List[LLMEndpointConfig]):
        """更新 LLM 端点配置"""
        endpoints_data = [
            {
                "name": ep.name,
                "api_base": ep.api_base,
                "api_key": ep.api_key,
                "model": ep.model,
                "priority": ep.priority
            }
            for ep in endpoints
        ]
        self.set("llm_endpoints", endpoints_data)
    
    def update_security_config(self, config: SecurityConfig):
        """更新安全配置"""
        security_data = {
            "command_whitelist": config.command_whitelist,
            "write_whitelist": config.write_whitelist,
            "enable_sandbox": config.enable_sandbox,
            "max_file_size": config.max_file_size
        }
        self.set("security", security_data)


# 全局配置实例
config_manager = ConfigManager()