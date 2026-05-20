"""
认证服务单元测试
"""
import pytest
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from seai.core.service.auth_service import AuthService


class TestAuthService:
    @pytest.fixture
    def auth_service(self):
        config = MagicMock()
        config.get = MagicMock(return_value="")
        return AuthService(config_manager=config)

    @pytest.fixture
    def auth_service_with_key(self):
        config = MagicMock()
        config.get = MagicMock(return_value="test-api-key-123")
        return AuthService(config_manager=config)

    def test_verify_no_key_configured(self, auth_service):
        assert auth_service.verify_api_key(None) is True
        assert auth_service.verify_api_key("any-key") is True

    def test_verify_correct_key(self, auth_service_with_key):
        assert auth_service_with_key.verify_api_key("test-api-key-123") is True

    def test_verify_wrong_key(self, auth_service_with_key):
        assert auth_service_with_key.verify_api_key("wrong-key") is False

    def test_verify_empty_key(self, auth_service_with_key):
        assert auth_service_with_key.verify_api_key(None) is False
        assert auth_service_with_key.verify_api_key("") is False

    def test_rate_limit_allows_requests(self, auth_service):
        for _ in range(60):
            assert auth_service.check_rate_limit("127.0.0.1") is True

    def test_rate_limit_blocks_excess(self, auth_service):
        for _ in range(60):
            auth_service.check_rate_limit("127.0.0.1")
        assert auth_service.check_rate_limit("127.0.0.1") is False

    def test_rate_limit_different_ips(self, auth_service):
        for _ in range(60):
            auth_service.check_rate_limit("192.168.1.1")
        assert auth_service.check_rate_limit("192.168.1.1") is False
        assert auth_service.check_rate_limit("192.168.1.2") is True

    def test_rate_limit_window_expiry(self, auth_service):
        auth_service.configure_rate_limit(window=1, max_requests=5)
        for _ in range(5):
            auth_service.check_rate_limit("10.0.0.1")
        assert auth_service.check_rate_limit("10.0.0.1") is False
        time.sleep(1.1)
        assert auth_service.check_rate_limit("10.0.0.1") is True

    def test_configure_rate_limit(self, auth_service):
        auth_service.configure_rate_limit(window=30, max_requests=10)
        assert auth_service._rate_limit_window == 30
        assert auth_service._rate_limit_max == 10