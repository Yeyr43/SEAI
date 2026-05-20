"""
认证服务
提供 API Key 验证和速率限制功能
"""
import time
from typing import Dict, Optional
from loguru import logger


class AuthService:
    def __init__(self, config_manager=None):
        self._config = config_manager
        self._rate_limit_store: Dict[str, list] = {}
        self._rate_limit_window = 60
        self._rate_limit_max = 60

    def verify_api_key(self, api_key: Optional[str]) -> bool:
        if not self._config:
            return True
        configured_key = self._config.get("api_key", "")
        if not configured_key:
            return True
        return api_key == configured_key

    def check_rate_limit(self, client_ip: str) -> bool:
        now = time.time()
        if client_ip not in self._rate_limit_store:
            self._rate_limit_store[client_ip] = []
        self._rate_limit_store[client_ip] = [
            t for t in self._rate_limit_store[client_ip]
            if now - t < self._rate_limit_window
        ]
        if len(self._rate_limit_store[client_ip]) >= self._rate_limit_max:
            return False
        self._rate_limit_store[client_ip].append(now)
        return True

    def is_api_key_configured(self) -> bool:
        """检查是否已配置 API Key"""
        configured_key = self._config.get("api_key", "") if self._config else ""
        return bool(configured_key)

    def configure_rate_limit(self, window: int = 60, max_requests: int = 60):
        self._rate_limit_window = window
        self._rate_limit_max = max_requests