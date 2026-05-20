"""Interface adapters — bridge existing SEAI interfaces to OODA Protocols.

Maps the full-featured interfaces from core/interfaces/ to the lightweight
Protocols defined in providers.py, so OODA stages can consume existing
components without modification.
"""
import time
from typing import Any
from loguru import logger


class MemoryAdapter:
    """Wraps a MemoryStore (15 methods) into OODA's MemoryProvider (3 async methods)."""

    def __init__(self, memory_store):
        self._store = memory_store

    async def search(self, query: str, top_k: int = 5,
                     filter_types: list[str] | None = None) -> list:
        try:
            results = self._store.search_memory(query, top_k=top_k)
        except Exception:
            logger.debug(f"MemoryAdapter.search failed for query={query[:80]}", exc_info=True)
            return []
        if filter_types:
            results = [r for r in results
                       if getattr(r, 'mem_type', 'unknown') in filter_types]
        return results

    async def get_profile(self, user_id: str) -> dict:
        try:
            return self._store.get_user_profile(user_id) or {}
        except Exception:
            logger.debug(f"MemoryAdapter.get_profile failed for user={user_id}", exc_info=True)
            return {}

    async def get_session_summary(self, session_id: str) -> str | None:
        try:
            return self._store.get_session_summary(session_id)
        except Exception:
            logger.debug(f"MemoryAdapter.get_session_summary failed for session={session_id}", exc_info=True)
            return None


class KGAdapter:
    """Wraps a KnowledgeGraphManager into OODA's KGProvider.

    KnowledgeGraphManager.search(query, depth, top_k) → OODA KGProvider.query(entities)
    """

    def __init__(self, kg_store=None, cache_ttl_s: float = 60.0):
        self._kg = kg_store
        self._cache_ttl_s = cache_ttl_s
        self._cache: dict[str, tuple[float, list]] = {}

    async def query(self, entities: list[str], hop: int = 1,
                    relation_types: list[str] | None = None) -> list:
        if self._kg is None:
            return []

        cache_key = f"{' '.join(sorted(entities))}|{hop}|{relation_types}"
        now = time.time()
        if cache_key in self._cache:
            cached_at, cached_result = self._cache[cache_key]
            if now - cached_at < self._cache_ttl_s:
                return cached_result

        try:
            query_str = " ".join(entities)
            results = self._kg.search(query_str, depth=hop, top_k=5)
            from seai.core.ooda.types import KGNode
            nodes = []
            for r in results:
                if isinstance(r, KGNode):
                    nodes.append(r)
                elif isinstance(r, dict):
                    nodes.append(KGNode(
                        entity=r.get("entity", str(r)),
                        relation=r.get("relation", ""),
                        target=r.get("target", ""),
                        confidence=r.get("confidence", 0.0),
                    ))
                else:
                    nodes.append(KGNode(
                        entity=getattr(r, "entity", str(r)),
                        relation=getattr(r, "relation", ""),
                        target=getattr(r, "target", ""),
                        confidence=getattr(r, "confidence", 0.0),
                    ))
            self._cache[cache_key] = (now, nodes)
            return nodes
        except Exception:
            logger.debug(f"KGAdapter.query failed for entities={entities}", exc_info=True)
            return []


class ToolExecutorAdapter:
    """Wraps a ToolExecutor (execute_tool) into the shape OODA ActStage expects.

    ActStage calls: tool_executor.execute(name, params) -> result
    ToolExecutor has: execute_tool(name, arguments) -> result
    """

    def __init__(self, tool_executor):
        self._te = tool_executor

    async def execute(self, name: str, params: dict) -> Any:
        return await self._te.execute_tool(name, params)

    def list_tools(self) -> list[dict]:
        try:
            return self._te.get_tool_definitions()
        except Exception:
            logger.debug("ToolExecutorAdapter.list_tools failed", exc_info=True)
            return []


class EventBusAdapter:
    """Wraps an event bus or provides empty defaults for OODA's EventBusProvider."""

    def __init__(self, event_bus=None):
        self._bus = event_bus

    def snapshot(self) -> tuple[list, dict]:
        if self._bus is None:
            return [], {}
        try:
            return self._bus.snapshot()
        except Exception:
            logger.debug("EventBusAdapter.snapshot failed", exc_info=True)
            return [], {}

    async def publish_evolution_signal(self, signal: dict) -> None:
        if self._bus is None:
            return
        try:
            await self._bus.publish_evolution_signal(signal)
        except Exception:
            logger.debug("EventBusAdapter.publish_evolution_signal failed", exc_info=True)

    def subscribe_evolution(self, handler) -> None:
        if self._bus is None:
            return
        try:
            self._bus.subscribe_evolution(handler)
        except Exception:
            logger.debug("EventBusAdapter.subscribe_evolution failed", exc_info=True)

    def circuit_status(self, name: str) -> str:
        """Return circuit state: 'closed', 'open', or 'half_open'."""
        if self._bus is None:
            return "closed"
        try:
            return self._bus.circuit_status(name)
        except Exception:
            logger.debug(f"EventBusAdapter.circuit_status failed for {name}", exc_info=True)
            return "closed"

    def circuit_on_success(self, name: str) -> None:
        if self._bus is None:
            return
        try:
            self._bus.circuit_on_success(name)
        except Exception:
            logger.debug(f"EventBusAdapter.circuit_on_success failed for {name}", exc_info=True)

    def circuit_on_failure(self, name: str) -> None:
        if self._bus is None:
            return
        try:
            self._bus.circuit_on_failure(name)
        except Exception:
            logger.debug(f"EventBusAdapter.circuit_on_failure failed for {name}", exc_info=True)
