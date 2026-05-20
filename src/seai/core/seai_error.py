"""
SEAI 统一错误协议 - 所有模块错误的基类
提供错误码、严重级别、可恢复性、上下文信息
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
import time
import uuid


class ErrorSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ErrorCategory(str, Enum):
    LLM = "llm"
    TOOL = "tool"
    MEMORY = "memory"
    SKILL = "skill"
    NETWORK = "network"
    FILE_SYSTEM = "file_system"
    CONSTRAINT = "constraint"
    AGENT = "agent"
    CONFIG = "config"
    INTERNAL = "internal"
    UNKNOWN = "unknown"


@dataclass
class SEAIError(Exception):
    message: str
    category: ErrorCategory = ErrorCategory.UNKNOWN
    severity: ErrorSeverity = ErrorSeverity.MEDIUM
    code: str = "SEAI-0000"
    recoverable: bool = True
    context: Dict[str, Any] = field(default_factory=dict)
    cause: Optional[Exception] = None
    error_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self):
        super().__init__(self.message)

    def to_dict(self) -> dict:
        return {
            "error_id": self.error_id,
            "code": self.code,
            "message": self.message,
            "category": self.category.value,
            "severity": self.severity.value,
            "recoverable": self.recoverable,
            "context": self.context,
            "cause": str(self.cause) if self.cause else None,
            "timestamp": self.timestamp,
        }


class LLMError(SEAIError):
    def __init__(self, message: str, **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.LLM,
            code=kwargs.pop("code", "SEAI-1001"),
            **kwargs,
        )


class ToolError(SEAIError):
    def __init__(self, message: str, tool_name: str = "", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.TOOL,
            code=kwargs.pop("code", "SEAI-2001"),
            context={"tool_name": tool_name, **kwargs.pop("context", {})},
            **kwargs,
        )


class ConstraintError(SEAIError):
    def __init__(self, message: str, boundary_type: str = "", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.CONSTRAINT,
            code=kwargs.pop("code", "SEAI-3001"),
            severity=ErrorSeverity.HIGH,
            context={"boundary_type": boundary_type, **kwargs.pop("context", {})},
            **kwargs,
        )


class AgentError(SEAIError):
    def __init__(self, message: str, agent_id: str = "", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.AGENT,
            code=kwargs.pop("code", "SEAI-4001"),
            context={"agent_id": agent_id, **kwargs.pop("context", {})},
            **kwargs,
        )


class ConfigError(SEAIError):
    def __init__(self, message: str, config_key: str = "", **kwargs):
        super().__init__(
            message=message,
            category=ErrorCategory.CONFIG,
            code=kwargs.pop("code", "SEAI-5001"),
            severity=ErrorSeverity.CRITICAL,
            recoverable=False,
            context={"config_key": config_key, **kwargs.pop("context", {})},
            **kwargs,
        )