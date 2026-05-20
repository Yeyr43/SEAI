"""Multi-turn OODA loop simulation — full pipeline with mock LLM.

Tests the complete Observe→Orient→Decide→Act cycle across multiple
iterations, verifying context threading, tool switching, evolution
signals, and result accumulation.
"""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from seai.core.ooda.types import (
    Intent, OODALoopConfig,
)
from seai.core.ooda.observe import ObserveStage
from seai.core.ooda.orient import OrientStage
from seai.core.ooda.decide import DecideStage
from seai.core.ooda.act import ActStage
from seai.core.ooda.loop import OODALoop


def _orient_json(strategy: str, capabilities: list[str], confidence: float = 0.9) -> str:
    """Build Orient-stage JSON for a given strategy."""
    import json
    return json.dumps({
        "strategy": strategy,
        "required_capabilities": capabilities,
        "gap_analysis": "ok",
        "confidence": confidence,
        "goal_description": f"Execute {strategy}",
        "sub_tasks": [],
        "estimated_tool_calls": 1,
        "fallback_strategy": None,
        "fallback_conditions": [],
    })


def _decide_json(tool_name: str, params: dict, confidence: float = 0.95,
                 fallback_name: str | None = None) -> str:
    """Build Decide-stage JSON for a given tool."""
    import json
    fallback = None
    if fallback_name:
        fallback = {
            "name": fallback_name,
            "params": {"query": params.get("query", "fallback")},
            "confidence": 0.5,
            "reason": "backup",
        }
    return json.dumps({
        "primary_tool": {
            "name": tool_name,
            "params": params,
            "confidence": confidence,
            "reason": "best match",
        },
        "fallback_tool": fallback,
        "side_tools": [],
        "retry_policy": {"max_retries": 1, "backoff": 0.1},
        "timeout_ms": 30000,
        "tool_context_prompt": "",
    })


class TestMultiTurnOODA:
    """Multi-turn OODA loop with mock LLM driving tool-switching decisions."""

    @pytest.fixture
    def mock_memory(self):
        mem = MagicMock()
        mem.search = AsyncMock(return_value=[])
        mem.get_profile = AsyncMock(return_value={})
        mem.get_session_summary = AsyncMock(return_value=None)
        return mem

    @pytest.fixture
    def mock_kg(self):
        kg = MagicMock()
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
    def mock_tool_executor(self):
        """Returns different results per iteration so we can verify ordering."""
        call_index = [0]
        results = [
            "search: Python asyncio guide found at /docs/async.md",
            "file: import asyncio; async def main(): ...",
            "bash: Hello from async main!",
        ]

        async def execute(name, params):
            idx = call_index[0]
            call_index[0] += 1
            return results[min(idx, len(results) - 1)]

        te = MagicMock()
        te.list_tools = MagicMock(return_value=[
            {"name": "web_search", "description": "Search the web"},
            {"name": "read_file", "description": "Read a file"},
            {"name": "bash", "description": "Run shell command"},
            {"name": "fetch_url", "description": "Fetch URL (fallback)"},
        ])
        te.execute = execute
        return te

    @pytest.fixture
    def multi_turn_llm(self):
        """LLM that drives a realistic 3-turn conversation through OODA.

        Turn 1: Orient→web_search, Decide→web_search for the query
        Turn 2: Orient→read_file, Decide→read_file for the result
        Turn 3: Orient→bash, Decide→bash to run the example
        """
        responses = [
            # Turn 1: Orient + Decide
            _orient_json("SERIAL", ["web_search"]),
            _decide_json("web_search", {"query": "Python asyncio guide"}),
            # Turn 2: Orient + Decide
            _orient_json("SERIAL", ["read_file"]),
            _decide_json("read_file", {"path": "/docs/async.md"}),
            # Turn 3: Orient + Decide
            _orient_json("SERIAL", ["bash"]),
            _decide_json("bash", {"command": "python async_example.py"}),
        ]
        llm = MagicMock()
        llm.chat = AsyncMock(side_effect=list(responses))
        return llm

    @pytest.fixture
    def loop(self, mock_memory, mock_kg, mock_event_bus, multi_turn_llm, mock_tool_executor):
        observe = ObserveStage(memory=mock_memory, kg=mock_kg, event_bus=mock_event_bus)
        orient = OrientStage(llm=multi_turn_llm, kg=mock_kg)
        decide = DecideStage(llm=multi_turn_llm, tool_executor=mock_tool_executor)
        act = ActStage(
            tool_executor=mock_tool_executor,
            memory=mock_memory, kg=mock_kg, event_bus=mock_event_bus,
        )
        return OODALoop(observe=observe, orient=orient, decide=decide, act=act)

    # ── Tests ──

    def test_three_turn_conversation_completes(self, loop):
        """Full 3-turn OODA loop completes with different tools per turn."""
        intent = Intent(raw="Help me run the async example", category="general", confidence=0.8)
        config = OODALoopConfig(max_iterations=3)

        result = asyncio.run(loop.run(intent, config))

        assert result.status == "completed"
        assert len(result.actions) == 3
        assert all(a.success for a in result.actions)

    def test_tools_switch_per_iteration(self, loop):
        """Each iteration uses the tool selected by the Orient→Decide pipeline."""
        intent = Intent(raw="multi-step task", category="general", confidence=0.8)
        config = OODALoopConfig(max_iterations=3)

        result = asyncio.run(loop.run(intent, config))

        tools_used = [a.primary_tool for a in result.actions]
        assert tools_used == ["web_search", "read_file", "bash"]

    def test_context_threads_across_turns(self, loop):
        """SituationContext.turn_count increments and results feed forward."""
        intent = Intent(raw="context test", category="general", confidence=0.8)
        config = OODALoopConfig(max_iterations=3)

        result = asyncio.run(loop.run(intent, config))

        assert result.situation.turn_count == 3
        # Tool results should be accumulated for next iterations
        assert len(result.situation.last_tool_results) >= 1

    def test_evolution_not_triggered_on_success(self, loop):
        """When all tools succeed, no evolution is triggered."""
        intent = Intent(raw="all good", category="general", confidence=0.8)
        config = OODALoopConfig(max_iterations=3, evolution_check_interval=1)

        result = asyncio.run(loop.run(intent, config))

        assert result.evolution_triggered is False

    def test_evolution_triggered_on_repeated_failures(self, mock_tool_executor,
                                                       multi_turn_llm, loop_factory):
        """When tools repeatedly fail, evolution is triggered."""
        # Override tool executor to always fail
        mock_tool_executor.execute = AsyncMock(side_effect=RuntimeError("down"))

        # Fresh loop with failing executor
        loop = loop_factory(mock_tool_executor, multi_turn_llm)

        intent = Intent(raw="will fail repeatedly", category="general", confidence=0.8)
        config = OODALoopConfig(max_iterations=3, evolution_check_interval=1)

        result = asyncio.run(loop.run(intent, config))

        assert result.evolution_triggered is True
        # Actions should still be recorded even if they failed
        assert len(result.actions) >= 1

    @pytest.fixture
    def loop_factory(self, mock_memory, mock_kg, mock_event_bus):
        """Factory for creating loops with custom tool_executor and llm."""
        def _make(tool_executor, llm):
            observe = ObserveStage(memory=mock_memory, kg=mock_kg, event_bus=mock_event_bus)
            orient = OrientStage(llm=llm, kg=mock_kg)
            decide = DecideStage(llm=llm, tool_executor=tool_executor)
            act = ActStage(
                tool_executor=tool_executor,
                memory=mock_memory, kg=mock_kg, event_bus=mock_event_bus,
            )
            return OODALoop(observe=observe, orient=orient, decide=decide, act=act)
        return _make

    def test_summary_includes_tool_sequence(self, loop):
        """The result summary mentions the tools that were used."""
        intent = Intent(raw="summary test", category="general", confidence=0.8)
        config = OODALoopConfig(max_iterations=3)

        result = asyncio.run(loop.run(intent, config))

        assert "web_search" in result.summary
        assert "read_file" in result.summary
        assert "bash" in result.summary

    def test_max_iterations_respected(self, loop):
        """Loop stops exactly at max_iterations, no overflow."""
        intent = Intent(raw="limit test", category="general", confidence=0.8)
        config = OODALoopConfig(max_iterations=2)

        result = asyncio.run(loop.run(intent, config))

        assert len(result.actions) == 2
        assert result.status == "completed"
