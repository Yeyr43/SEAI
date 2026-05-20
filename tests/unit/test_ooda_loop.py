"""OODALoop coordinator — full-loop integration tests."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from seai.core.ooda.types import (
    SituationContext, Intent, ActionPlan, Decision, ToolBinding,
    RetryPolicy, ActionResult, EvolutionSignal,
    OODALoopConfig, OODAResult, TaskGoal,
)
from seai.core.ooda.providers import MemoryProvider, KGProvider, EventBusProvider
from seai.core.ooda.observe import ObserveStage
from seai.core.ooda.orient import OrientStage
from seai.core.ooda.decide import DecideStage
from seai.core.ooda.act import ActStage
from seai.core.ooda.loop import OODALoop


class TestOODALoop:
    """Tests for the OODA loop coordinator — mock all stages."""

    @pytest.fixture
    def mock_memory(self):
        mem = MagicMock(spec=MemoryProvider)
        mem.search = AsyncMock(return_value=[])
        mem.get_profile = AsyncMock(return_value={})
        mem.get_session_summary = AsyncMock(return_value=None)
        return mem

    @pytest.fixture
    def mock_kg(self):
        kg = MagicMock(spec=KGProvider)
        kg.query = AsyncMock(return_value=[])
        return kg

    @pytest.fixture
    def mock_event_bus(self):
        bus = MagicMock()
        bus.snapshot = MagicMock(return_value=([], {}))
        bus.circuit_status = MagicMock(return_value="closed")
        bus.circuit_on_success = MagicMock()
        bus.circuit_on_failure = MagicMock()
        bus.publish_evolution_signal = AsyncMock()
        return bus

    @pytest.fixture
    def mock_llm(self):
        orient_json = (
            '{"strategy": "SERIAL", "required_capabilities": ["web_search"], '
            '"gap_analysis": "ok", "confidence": 0.9, '
            '"goal_description": "find info", "sub_tasks": [], '
            '"estimated_tool_calls": 1, "fallback_strategy": null, '
            '"fallback_conditions": []}'
        )
        decide_json = (
            '{"primary_tool": {"name": "web_search", "params": {"query": "Python"}, '
            '"confidence": 0.95, "reason": "best match"}, '
            '"fallback_tool": null, '
            '"side_tools": [], '
            '"retry_policy": {"max_retries": 1, "backoff": 0.5}, '
            '"timeout_ms": 30000, '
            '"tool_context_prompt": ""}'
        )
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=[orient_json, decide_json] * 10)
        return llm

    @pytest.fixture
    def mock_tool_executor(self):
        te = MagicMock()
        te.list_tools = MagicMock(return_value=[
            {"name": "web_search", "description": "Search the web"},
            {"name": "fetch_url", "description": "Fetch a URL"},
        ])
        te.execute = AsyncMock(return_value="success output")
        return te

    @pytest.fixture
    def loop(self, mock_memory, mock_kg, mock_event_bus, mock_llm, mock_tool_executor):
        observe = ObserveStage(memory=mock_memory, kg=mock_kg, event_bus=mock_event_bus)
        orient = OrientStage(llm=mock_llm, kg=mock_kg)
        decide = DecideStage(llm=mock_llm, tool_executor=mock_tool_executor)
        act = ActStage(
            tool_executor=mock_tool_executor,
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
        )
        return OODALoop(observe=observe, orient=orient, decide=decide, act=act)

    @pytest.fixture
    def intent(self):
        return Intent(raw="search for Python", category="code_search", confidence=0.9)

    # ── Single iteration ──

    def test_single_iteration_completes(self, loop, intent):
        """A single OODA iteration runs all four stages and returns results."""
        config = OODALoopConfig(max_iterations=1)
        result = asyncio.run(loop.run(intent, config))

        assert isinstance(result, OODAResult)
        assert result.status == "completed"
        assert len(result.actions) == 1
        assert result.actions[0].success is True
        assert result.actions[0].primary_tool == "web_search"

    def test_single_iteration_produces_summary(self, loop, intent):
        """OODAResult includes a human-readable summary."""
        config = OODALoopConfig(max_iterations=1)
        result = asyncio.run(loop.run(intent, config))

        assert len(result.summary) > 0
        assert "web_search" in result.summary

    # ── Multi-iteration ──

    def test_multi_iteration_accumulates_actions(self, loop, intent):
        """Multiple iterations accumulate ActionResult entries."""
        config = OODALoopConfig(max_iterations=3)
        result = asyncio.run(loop.run(intent, config))

        assert result.status == "completed"
        assert len(result.actions) == 3
        for a in result.actions:
            assert a.success is True

    def test_multi_iteration_feeds_context_forward(self, loop, intent, mock_tool_executor):
        """Each iteration's results influence the next Observe cycle."""
        call_params = []

        async def capture(name, params):
            call_params.append(params)
            return f"iteration {len(call_params)}"

        mock_tool_executor.execute = capture

        config = OODALoopConfig(max_iterations=2)
        result = asyncio.run(loop.run(intent, config))

        # Each iteration's tool should have been called
        assert len(call_params) == 2
        assert len(result.actions) == 2

    # ── Stop conditions ──

    def test_max_iterations_stops_loop(self, loop, intent):
        """Loop stops when max_iterations is reached."""
        config = OODALoopConfig(max_iterations=2)
        result = asyncio.run(loop.run(intent, config))

        assert result.status == "completed"
        assert len(result.actions) == 2

    def test_context_exhausted_stops_loop(self, loop, intent):
        """Loop stops early when context is exhausted."""
        # Set context_usage_ratio above critical threshold
        config = OODALoopConfig(
            max_iterations=10,
            context_critical_ratio=0.5,
        )

        # Patch observe to simulate context exhaustion after first iteration
        original_gather = loop._observe.gather
        call_count = [0]

        async def exhausting_gather(situation):
            call_count[0] += 1
            ctx = await original_gather(situation)
            if call_count[0] > 1:
                ctx.context_usage_ratio = 0.9  # above critical
            return ctx

        loop._observe.gather = exhausting_gather

        result = asyncio.run(loop.run(intent, config))

        assert result.status == "context_exhausted"
        assert len(result.actions) < 10

    # ── Evolution signals ──

    def test_evolution_triggered_after_repeated_failures(self, loop, intent, mock_tool_executor):
        """Repeated tool failures across iterations trigger evolution."""
        mock_tool_executor.execute = AsyncMock(side_effect=RuntimeError("tool down"))

        config = OODALoopConfig(
            max_iterations=3,
            evolution_check_interval=1,
        )
        result = asyncio.run(loop.run(intent, config))

        # Evolution should be triggered after multiple failures
        assert result.evolution_triggered is True

    # ── Error handling ──

    def test_loop_handles_orient_failure_gracefully(self, loop, intent, mock_llm):
        """If Orient fails, loop uses fallback and continues."""
        mock_llm.chat = AsyncMock(side_effect=Exception("LLM down"))

        config = OODALoopConfig(max_iterations=1)
        result = asyncio.run(loop.run(intent, config))

        # Should still complete with a fallback plan
        assert result.status == "completed"
        assert len(result.actions) == 1

    def test_loop_preserves_situation_across_iterations(self, loop, intent):
        """The SituationContext is passed forward between iterations."""
        config = OODALoopConfig(max_iterations=2)
        result = asyncio.run(loop.run(intent, config))

        # Final situation should reflect accumulated state
        assert result.situation is not None
        assert result.situation.turn_count >= 2
