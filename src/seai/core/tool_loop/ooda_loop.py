"""OODAToolLoopEngine — OODA-powered alternative to ToolLoopEngine.

Same interface (run_tool_loop, process_sync) but internally uses the
OODA four-stage loop: Observe → Orient → Decide → Act.

Can be swapped in via configuration without changing any callers.
"""
from typing import List, Dict, Any

from seai.core.ooda.adapters import (
    MemoryAdapter, KGAdapter, ToolExecutorAdapter, EventBusAdapter,
)
from seai.core.ooda.loop import OODALoop
from seai.core.ooda.observe import ObserveStage
from seai.core.ooda.orient import OrientStage
from seai.core.ooda.decide import DecideStage
from seai.core.ooda.act import ActStage
from seai.core.ooda.types import OODAConfig, CircuitConfig
from seai.core.ooda.event_bus import OODAEventBus
from seai.core.ooda.evolution_bridge import EvolutionBridge
from .tool_selector import detect_intent


class OODAToolLoopEngine:
    """OODA-based tool loop engine — drop-in replacement for ToolLoopEngine."""

    def __init__(self, llm_provider=None, tool_executor=None, skill_system=None,
                 skill_repository=None, memory_store=None, error_handler=None,
                 evolution_service=None, conversation_service=None, feedback_loop=None,
                 data_dir=None, circuit_breaker=None, security=None,
                 ooda_config: OODAConfig | None = None):
        self.llm_provider = llm_provider
        self.tool_executor = tool_executor
        self.memory_store = memory_store
        cfg = ooda_config or OODAConfig()

        # Build OODA adapters from existing components
        memory = MemoryAdapter(memory_store) if memory_store else _NOOP_MEMORY
        kg = _build_kg_adapter()
        tool_adapter = ToolExecutorAdapter(tool_executor) if tool_executor else _NOOP_TOOL

        # Create event bus with configurable circuit breaker
        self._event_bus = OODAEventBus(
            max_history=cfg.event_max_history,
            default_circuit_config=cfg.circuit,
            tool_circuit_configs=cfg.tool_circuits,
        )
        event_bus = EventBusAdapter(self._event_bus)

        # Wire EvolutionBridge with configurable thresholds
        self._evolution_bridge = None
        if evolution_service and feedback_loop:
            self._evolution_bridge = EvolutionBridge(
                event_bus=self._event_bus,
                evolution_service=evolution_service,
                feedback_loop=feedback_loop,
                failure_threshold=cfg.evolution_failure_threshold,
                deep_evolve_threshold=cfg.evolution_deep_evolve_threshold,
                window_s=cfg.evolution_window_s,
                deep_evolve_cooldown_s=cfg.evolution_deep_evolve_cooldown_s,
            )

        # Wire OODA stages with configurable timeouts
        observe = ObserveStage(
            memory=memory, kg=kg, event_bus=event_bus,
            timeout_ms=cfg.observe_timeout_ms,
        )
        orient = OrientStage(
            llm=llm_provider, kg=kg,
            timeout_ms=cfg.orient_timeout_ms,
            cache_ttl_s=cfg.orient_cache_ttl_s,
        )
        decide = DecideStage(
            llm=llm_provider, tool_executor=tool_adapter,
            timeout_ms=cfg.decide_timeout_ms,
        )
        act = ActStage(
            tool_executor=tool_adapter,
            memory=memory, kg=kg, event_bus=event_bus,
        )
        self._loop = OODALoop(observe=observe, orient=orient, decide=decide, act=act)

        # Store adapters for access
        self._memory = memory
        self._kg = kg

    async def run_tool_loop(self, messages: List[Dict], tools: List[Dict],
                            max_rounds: int = 12) -> str:
        """Run the OODA loop — compatible with ToolLoopEngine.run_tool_loop."""
        intent = self._extract_intent(messages)
        config = OODAConfig(max_iterations=max_rounds)

        result = await self._loop.run(intent, config)

        if not result.actions:
            return result.summary

        # Build final response from the last successful action result
        last_with_output = None
        for action in reversed(result.actions):
            if action.primary_result and action.success:
                last_with_output = action
                break

        if last_with_output:
            return str(last_with_output.primary_result)

        return result.summary

    async def process_sync(self, messages: List[Dict], tools: List[Dict]) -> str:
        """Synchronous-compatible entry point — delegates to run_tool_loop."""
        return await self.run_tool_loop(messages, tools)

    @staticmethod
    def _extract_intent(messages: List[Dict]) -> Any:
        from seai.core.ooda.types import Intent
        query = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                query = m.get("content", "")
                break
        if not query:
            query = "process request"
        category = detect_intent(query) if query else "general"
        return Intent(raw=query, category=category, confidence=0.8)


# ── No-op fallbacks ──

class _NoopMemory:
    async def search(self, *a, **kw): return []
    async def get_profile(self, *a, **kw): return {}
    async def get_session_summary(self, *a, **kw): return None


class _NoopTool:
    async def execute(self, *a, **kw): return ""
    def list_tools(self, *a, **kw): return []


_NOOP_MEMORY = _NoopMemory()
_NOOP_TOOL = _NoopTool()


def _build_kg_adapter():
    """Try to wire the real KnowledgeGraphManager, fall back to no-op."""
    try:
        from seai.core._rust import get_knowledge_graph
        kg_manager = get_knowledge_graph()
        if kg_manager:
            return KGAdapter(kg_manager)
    except Exception:
        pass
    return KGAdapter()
