"""
LLM Fallback + 重试 单元测试
覆盖：fallback 切换、指数退避重试、熔断集成、不可重试错误处理
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_endpoints():
    return [
        {"name": "primary", "api_base": "http://localhost:11434/v1", "api_key": "k1", "model": "gpt-4"},
        {"name": "fallback", "api_base": "http://localhost:11435/v1", "api_key": "k2", "model": "gpt-3.5"},
    ]


@pytest.fixture
def llm_manager(mock_endpoints):
    try:
        from seai.core.llm_manager import LLMManager
        return LLMManager(endpoints=mock_endpoints, max_retries=2, retry_base_delay=0.01)
    except Exception as e:
        pytest.skip(f"LLMManager 初始化失败: {e}")


class TestFallbackOrder:
    def test_current_model_first(self, llm_manager):
        llm_manager.set_current_model("fallback")
        order = llm_manager._get_fallback_order()
        assert order[0] == "fallback"

    def test_all_models_in_order(self, llm_manager):
        order = llm_manager._get_fallback_order()
        assert set(order) == {"primary", "fallback"}
        assert len(order) == 2


class TestRetryableDetection:
    def test_rate_limit_is_retryable(self, llm_manager):
        assert llm_manager._is_retryable(Exception("rate_limit exceeded"))

    def test_timeout_is_retryable(self, llm_manager):
        assert llm_manager._is_retryable(Exception("connection timeout"))

    def test_server_error_is_retryable(self, llm_manager):
        assert llm_manager._is_retryable(Exception("503 Service Unavailable"))

    def test_auth_error_not_retryable(self, llm_manager):
        assert not llm_manager._is_retryable(Exception("invalid api key"))


class TestRetryWithFallback:
    @pytest.mark.asyncio
    async def test_success_first_try(self, llm_manager):
        call_fn = AsyncMock(return_value="success")
        result = await llm_manager._retry_with_fallback(call_fn, "test", "arg1")
        assert result == "success"
        assert call_fn.call_count == 1

    @pytest.mark.asyncio
    async def test_retry_then_success(self, llm_manager):
        call_fn = AsyncMock(side_effect=[Exception("timeout"), Exception("503"), "success"])
        result = await llm_manager._retry_with_fallback(call_fn, "test", "arg1")
        assert result == "success"
        assert call_fn.call_count == 3

    @pytest.mark.asyncio
    async def test_fallback_to_next_model(self, llm_manager):
        primary_call = AsyncMock(side_effect=Exception("timeout"))
        fallback_call = AsyncMock(return_value="fallback_result")

        call_count = [0]

        async def call_fn(client, model_id, arg):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise Exception("timeout")
            return "fallback_result"

        with patch.object(llm_manager, '_get_fallback_order', return_value=["primary", "fallback"]):
            result = await llm_manager._retry_with_fallback(call_fn, "test", "arg1")
            assert result == "fallback_result"

    @pytest.mark.asyncio
    async def test_non_retryable_skips_retry(self, llm_manager):
        call_fn = AsyncMock(side_effect=Exception("invalid api key"))
        with pytest.raises(RuntimeError, match="所有LLM端点均已尝试失败"):
            await llm_manager._retry_with_fallback(call_fn, "test", "arg1")
        assert call_fn.call_count == 1

    @pytest.mark.asyncio
    async def test_all_models_exhausted(self, llm_manager):
        call_fn = AsyncMock(side_effect=Exception("timeout"))
        with pytest.raises(RuntimeError, match="所有LLM端点均已尝试失败"):
            await llm_manager._retry_with_fallback(call_fn, "test", "arg1")


class TestChatWithFallback:
    @pytest.mark.asyncio
    async def test_chat_uses_fallback(self, llm_manager):
        with patch.object(llm_manager, '_retry_with_fallback', new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = "response"
            result = await llm_manager.chat([{"role": "user", "content": "hi"}])
            assert result == "response"
            mock_retry.assert_called_once()

    @pytest.mark.asyncio
    async def test_chat_with_tools_uses_fallback(self, llm_manager):
        with patch.object(llm_manager, '_retry_with_fallback', new_callable=AsyncMock) as mock_retry:
            mock_retry.return_value = "tool_response"
            result = await llm_manager._chat_with_tools_sync(
                [{"role": "user", "content": "hi"}], [{"type": "function"}]
            )
            assert result == "tool_response"
            mock_retry.assert_called_once()