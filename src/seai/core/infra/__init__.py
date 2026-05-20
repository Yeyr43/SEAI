"""
SEAI Infrastructure Layer - Cross-cutting infrastructure and utility modules.

Contains:
- config: ConfigManager, Config classes
- database: DatabaseManager, AsyncDatabaseManager, SQLAlchemy models
- security: SecurityManager
- crypto: Encryption/decryption utilities
- net: Web search enable/disable and search functions
- lazy: LazyImport for deferred module loading
- health: HealthChecker, HealthReport, HealthStatus, SystemHealth
- permissions: PermissionManager, Permission, ExecutionPhase, role permissions
- lifecycle: AgentLifecycleManager
- resource_manager: ResourceEventHandler, ResourceManager (hot-reload)
- terminal: TerminalManager (WebSocket logging)
"""
from .config import (
    ConfigManager,
    LLMEndpointConfig,
    SecurityConfig,
    MemoryConfig,
    SystemConfig,
    config_manager,
)
from .database import (
    DatabaseManager,
    AsyncDatabaseManager,
    db_manager,
    async_db_manager,
    init_db,
    get_db,
    SessionModel,
    MessageModel,
    MemoryModel,
    SkillModel,
    EvolutionLogModel,
    AuditLogModel,
    Base,
)
from .security import SecurityManager
from .crypto import (
    encrypt_value,
    decrypt_value,
    is_encrypted,
    encrypt_sensitive_config,
    decrypt_sensitive_config,
)
from .net import enable, disable, is_enabled, set_enabled, web_search
from .lazy import LazyImport
from .health import (
    HealthChecker,
    HealthReport,
    HealthStatus,
    SystemHealth,
    health_checker,
)
from .permissions import (
    PermissionManager,
    Permission,
    ExecutionPhase,
    PLAN_MODE,
    EXECUTION_MODE,
    RESTRICTED_MODE,
    ROLE_PERMISSIONS,
    permission_manager,
)
from .lifecycle import AgentLifecycleManager
from .resource_manager import ResourceEventHandler, ResourceManager
from .terminal import TerminalManager

__all__ = [
    # config
    "ConfigManager",
    "LLMEndpointConfig",
    "SecurityConfig",
    "MemoryConfig",
    "SystemConfig",
    "config_manager",
    # database
    "DatabaseManager",
    "AsyncDatabaseManager",
    "db_manager",
    "async_db_manager",
    "init_db",
    "get_db",
    "SessionModel",
    "MessageModel",
    "MemoryModel",
    "SkillModel",
    "EvolutionLogModel",
    "AuditLogModel",
    "Base",
    # security
    "SecurityManager",
    # crypto
    "encrypt_value",
    "decrypt_value",
    "is_encrypted",
    "encrypt_sensitive_config",
    "decrypt_sensitive_config",
    # net
    "enable",
    "disable",
    "is_enabled",
    "set_enabled",
    "web_search",
    # lazy
    "LazyImport",
    # health
    "HealthChecker",
    "HealthReport",
    "HealthStatus",
    "SystemHealth",
    "health_checker",
    # permissions
    "PermissionManager",
    "Permission",
    "ExecutionPhase",
    "PLAN_MODE",
    "EXECUTION_MODE",
    "RESTRICTED_MODE",
    "ROLE_PERMISSIONS",
    "permission_manager",
    # lifecycle
    "AgentLifecycleManager",
    # resource_manager
    "ResourceEventHandler",
    "ResourceManager",
    # terminal
    "TerminalManager",
]
