"""
SEAI Interfaces Layer - Abstract base classes and factories for core components.

Provides dependency inversion: all concrete implementations depend on these
abstract interfaces, enabling swappable backends for LLM, memory, skills, and tools.
"""
from .llm_provider import LLMProvider, LLMProviderFactory
from .memory_store import MemoryStore, MemoryStoreFactory
from .skill_repository import SkillRepository, SkillRepositoryFactory
from .tool_executor import ToolExecutor, ToolExecutorFactory

__all__ = [
    "LLMProvider",
    "LLMProviderFactory",
    "MemoryStore",
    "MemoryStoreFactory",
    "SkillRepository",
    "SkillRepositoryFactory",
    "ToolExecutor",
    "ToolExecutorFactory",
]
