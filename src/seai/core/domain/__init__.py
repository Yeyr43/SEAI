"""
SEAI Domain Layer - Core domain models, errors, and protocols.

Contains:
- errors: SEAIError, ErrorSeverity, ErrorCategory, SmartErrorHandler
- circuit_breaker: CircuitBreaker, CircuitBreakerManager
- protocols: TaskCard, Heartbeat, AgentMessage, EvolutionSignal
"""
from .errors import (
    SEAIError,
    ErrorSeverity,
    ErrorCategory,
    LLMError,
    ToolError,
    ConstraintError,
    AgentError,
    ConfigError,
    SmartErrorHandler,
    ErrorDiagnosis,
    ErrorPattern,
)

from .circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerManager,
    CircuitState,
    CircuitStats,
    breaker_manager,
)

from .protocols import (
    TaskStatus,
    TaskCard,
    Heartbeat,
    AgentMessage,
    EvolutionSignal,
)

__all__ = [
    "SEAIError",
    "ErrorSeverity",
    "ErrorCategory",
    "LLMError",
    "ToolError",
    "ConstraintError",
    "AgentError",
    "ConfigError",
    "SmartErrorHandler",
    "ErrorDiagnosis",
    "ErrorPattern",
    "CircuitBreaker",
    "CircuitBreakerManager",
    "CircuitState",
    "CircuitStats",
    "breaker_manager",
    "TaskStatus",
    "TaskCard",
    "Heartbeat",
    "AgentMessage",
    "EvolutionSignal",
]
