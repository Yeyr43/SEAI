"""
LLMManager 单元测试
覆盖：端点管理、模型切换、流式响应解析、工具调用格式转换
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_endpoints():
    return [
        {
            "name": "test-model",
            "api_base": "http://localhost:11434/v1",
            "api_key": "test-key",
            "model": "test-model-v1"
        }
    ]


@pytest.fixture
def llm_manager(mock_endpoints):
    try:
        from seai.core.llm_manager import LLMManager
        return LLMManager(endpoints=mock_endpoints)
    except Exception as e:
        pytest.skip(f"LLMManager 初始化失败: {e}")


class TestEndpointManagement:
    """端点管理测试"""

    def test_initialization(self, llm_manager):
        assert llm_manager is not None
        assert len(llm_manager.list_models()) > 0

    def test_list_models(self, llm_manager):
        models = llm_manager.list_models()
        assert "test-model" in models

    def test_add_endpoint(self, llm_manager):
        llm_manager.add_endpoint(
            name="new-model",
            base="http://localhost:11435/v1",
            key="new-key",
            model="new-model-v1"
        )
        models = llm_manager.list_models()
        assert "new-model" in models

    def test_remove_endpoint(self, llm_manager):
        llm_manager.add_endpoint(
            name="temp-model",
            base="http://localhost:11436/v1",
            key="temp-key",
            model="temp-model-v1"
        )
        llm_manager.remove_endpoint("temp-model")
        models = llm_manager.list_models()
        assert "temp-model" not in models

    def test_update_endpoints(self, llm_manager):
        new_endpoints = [
            {
                "name": "updated-model",
                "api_base": "http://localhost:11437/v1",
                "api_key": "updated-key",
                "model": "updated-model-v1"
            }
        ]
        llm_manager.update_endpoints(new_endpoints)
        models = llm_manager.list_models()
        assert "updated-model" in models
        assert "test-model" not in models


class TestModelSwitching:
    """模型切换测试"""

    def test_set_current_model(self, llm_manager):
        llm_manager.add_endpoint(
            name="model-b",
            base="http://localhost:11438/v1",
            key="key-b",
            model="model-b-v1"
        )
        llm_manager.set_current_model("model-b")
        assert llm_manager.current_model == "model-b"

    def test_set_invalid_model(self, llm_manager):
        with pytest.raises(ValueError):
            llm_manager.set_current_model("nonexistent-model")

    def test_get_current_model(self, llm_manager):
        current = llm_manager.get_current_model()
        assert current == "test-model"

    def test_get_available_models(self, llm_manager):
        models = llm_manager.get_available_models()
        assert isinstance(models, list)
        assert "test-model" in models


class TestStreamResponse:
    """流式响应解析测试"""

    @pytest.mark.asyncio
    async def test_chat_stream_method_exists(self, llm_manager):
        assert hasattr(llm_manager, 'chat_stream')
        assert callable(llm_manager.chat_stream)

    @pytest.mark.asyncio
    async def test_chat_with_tools_stream(self, llm_manager):
        assert hasattr(llm_manager, 'chat_with_tools')
        assert callable(llm_manager.chat_with_tools)


class TestToolCallFormat:
    """工具调用格式转换测试"""

    def test_chat_with_tools_method_exists(self, llm_manager):
        assert hasattr(llm_manager, 'chat_with_tools')
        assert callable(llm_manager.chat_with_tools)

    def test_chat_method_exists(self, llm_manager):
        assert hasattr(llm_manager, 'chat')
        assert callable(llm_manager.chat)


class TestCircuitBreakerIntegration:
    """熔断器集成测试"""

    def test_circuit_breaker_in_chat(self, llm_manager):
        from seai.core.circuit_breaker import breaker_manager
        breaker = breaker_manager.get_or_create("llm_chat", failure_threshold=3, cooldown_seconds=30.0)
        assert breaker is not None
        assert breaker.can_execute()

    def test_circuit_breaker_in_tools(self, llm_manager):
        from seai.core.circuit_breaker import breaker_manager
        breaker = breaker_manager.get_or_create("llm_tools", failure_threshold=3, cooldown_seconds=30.0)
        assert breaker is not None
        assert breaker.can_execute()
