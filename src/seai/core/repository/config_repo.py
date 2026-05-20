"""
配置数据仓库
封装配置文件的读写操作，集成加密存储
"""
from pathlib import Path
from typing import Dict, Any, Optional
from .base import BaseRepository
from ..crypto import encrypt_sensitive_config, decrypt_sensitive_config

_SENSITIVE_KEYS = ["api_key", "github_token"]


class ConfigRepository(BaseRepository[Dict]):
    def __init__(self, config_path: Path):
        super().__init__()
        self.config_path = config_path

    def load(self) -> Dict[str, Any]:
        raw = self._read_json(self.config_path, {})
        return decrypt_sensitive_config(raw, _SENSITIVE_KEYS)

    def save(self, config: Dict[str, Any]) -> bool:
        to_save = encrypt_sensitive_config(config, _SENSITIVE_KEYS)
        return self._write_json(self.config_path, to_save)

    def get(self, key: str, default: Any = None) -> Any:
        config = self.load()
        return config.get(key, default)

    def set(self, key: str, value: Any) -> bool:
        config = self.load()
        config[key] = value
        return self.save(config)

    def update(self, updates: Dict[str, Any]) -> bool:
        config = self.load()
        config.update(updates)
        return self.save(config)