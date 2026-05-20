"""
测试 SEAI 统一错误协议
"""
import pytest
from seai.core.seai_error import (
    SEAIError, LLMError, ToolError, ConstraintError,
    AgentError, ConfigError, ErrorSeverity, ErrorCategory,
)


class TestSEAIError:
    def test_base_error(self):
        error = SEAIError("test message")
        assert error.message == "test message"
        assert error.category == ErrorCategory.UNKNOWN
        assert error.severity == ErrorSeverity.MEDIUM
        assert error.code == "SEAI-0000"
        assert error.recoverable is True
        assert error.error_id is not None

    def test_error_to_dict(self):
        error = SEAIError("test", category=ErrorCategory.TOOL, code="SEAI-2001")
        d = error.to_dict()
        assert d["message"] == "test"
        assert d["category"] == "tool"
        assert d["code"] == "SEAI-2001"
        assert d["recoverable"] is True

    def test_llm_error(self):
        error = LLMError("LLM connection failed")
        assert error.category == ErrorCategory.LLM
        assert error.code == "SEAI-1001"

    def test_tool_error(self):
        error = ToolError("Tool failed", tool_name="read_file")
        assert error.category == ErrorCategory.TOOL
        assert error.code == "SEAI-2001"
        assert error.context["tool_name"] == "read_file"

    def test_constraint_error(self):
        error = ConstraintError("Access denied", boundary_type="file_write")
        assert error.category == ErrorCategory.CONSTRAINT
        assert error.code == "SEAI-3001"
        assert error.severity == ErrorSeverity.HIGH
        assert error.context["boundary_type"] == "file_write"

    def test_agent_error(self):
        error = AgentError("Agent failed", agent_id="agent-1")
        assert error.category == ErrorCategory.AGENT
        assert error.code == "SEAI-4001"
        assert error.context["agent_id"] == "agent-1"

    def test_config_error(self):
        error = ConfigError("Config missing", config_key="api_key")
        assert error.category == ErrorCategory.CONFIG
        assert error.code == "SEAI-5001"
        assert error.severity == ErrorSeverity.CRITICAL
        assert error.recoverable is False

    def test_custom_code(self):
        error = ToolError("Custom", code="SEAI-2999")
        assert error.code == "SEAI-2999"

    def test_cause_chain(self):
        cause = ValueError("root cause")
        error = SEAIError("wrapper", cause=cause)
        assert error.cause is cause
        assert "root cause" in error.to_dict()["cause"]

    def test_is_exception(self):
        error = SEAIError("test")
        assert isinstance(error, Exception)

        with pytest.raises(SEAIError):
            raise error

    def test_context_merge(self):
        error = ToolError("test", tool_name="test_tool", context={"extra": "data"})
        assert error.context["tool_name"] == "test_tool"
        assert error.context["extra"] == "data"