"""Act stage: tool execution with retry, fallback, and evolution signals."""
import asyncio
from unittest.mock import AsyncMock, MagicMock, call
import pytest

from seai.core.ooda.types import (
    SituationContext, Intent, Decision, ToolBinding, RetryPolicy,
    ActionResult, EvolutionSignal,
)
from seai.core.ooda.providers import MemoryProvider, KGProvider, EventBusProvider
from seai.core.ooda.act import ActStage


class TestActStage:
    """Act stage tests — pure unit, no LLM dependency."""

    @pytest.fixture
    def tool_executor(self):
        te = MagicMock()
        te.execute = AsyncMock(return_value="tool output: success")
        return te

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
    def situation(self):
        return SituationContext(
            intent=Intent(raw="search for Python", category="code_search", confidence=0.9),
        )

    @pytest.fixture
    def simple_decision(self):
        return Decision(
            primary_tool=ToolBinding(name="web_search", params={"query": "Python"}, confidence=0.9, reason="best match"),
            fallback_tool=None,
            side_tools=[],
            retry_policy=RetryPolicy(max_retries=1, backoff=0.1),
            timeout_ms=10_000,
            tool_context_prompt="",
        )

    @pytest.fixture
    def act_stage(self, tool_executor, mock_memory, mock_kg, mock_event_bus):
        return ActStage(
            tool_executor=tool_executor,
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
        )

    # ── Primary tool execution ──

    def test_execute_primary_tool_returns_success(self, act_stage, simple_decision, situation):
        """Primary tool succeeds → ActionResult with success=True."""
        result = asyncio.run(act_stage.execute(simple_decision, situation))

        assert isinstance(result, ActionResult)
        assert result.success is True
        assert result.primary_tool == "web_search"
        assert result.primary_result == "tool output: success"
        assert result.fallback_used is False
        assert result.elapsed_ms >= 0

    def test_execute_primary_tool_with_complex_params(self, act_stage, situation, tool_executor):
        """Tool receives the exact params from ToolBinding."""
        decision = Decision(
            primary_tool=ToolBinding(
                name="bash",
                params={"command": "cargo build --release", "cwd": "/project"},
                confidence=0.95,
                reason="build",
            ),
            retry_policy=RetryPolicy(max_retries=0, backoff=1.0),
        )

        asyncio.run(act_stage.execute(decision, situation))

        tool_executor.execute.assert_awaited_once_with("bash", {"command": "cargo build --release", "cwd": "/project"})

    # ── Fallback chain ──

    def test_fallback_used_when_primary_fails(self, act_stage, situation, tool_executor):
        """Primary fails → fallback is attempted → ActionResult reflects it."""
        tool_executor.execute = AsyncMock(side_effect=[
            RuntimeError("primary failed"),
            "fallback result",
        ])

        decision = Decision(
            primary_tool=ToolBinding(name="web_search", params={"query": "test"}, confidence=0.9, reason=""),
            fallback_tool=ToolBinding(name="fetch_url", params={"url": ""}, confidence=0.5, reason="backup"),
            retry_policy=RetryPolicy(max_retries=0, backoff=1.0),
        )

        result = asyncio.run(act_stage.execute(decision, situation))

        assert result.fallback_used is True
        assert result.fallback_tool == "fetch_url"
        assert result.fallback_result == "fallback result"
        assert result.primary_error is not None

    def test_retry_before_fallback(self, act_stage, situation, tool_executor):
        """Primary tool is retried max_retries times before fallback."""
        call_count = 0

        async def flaky_execute(name, params):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("transient error")
            return "success after retry"

        tool_executor.execute = flaky_execute

        decision = Decision(
            primary_tool=ToolBinding(name="bash", params={"command": "ls"}, confidence=0.9, reason=""),
            retry_policy=RetryPolicy(max_retries=2, backoff=0.01),
        )

        result = asyncio.run(act_stage.execute(decision, situation))

        assert result.success is True
        assert result.primary_result == "success after retry"
        assert call_count == 3  # initial + 2 retries

    # ── Side tools ──

    def test_side_tools_executed_in_parallel(self, act_stage, situation, tool_executor):
        """Side tools run alongside primary tool."""
        results = []

        async def track(name, params):
            results.append(name)
            return f"ok:{name}"

        tool_executor.execute = track

        decision = Decision(
            primary_tool=ToolBinding(name="web_search", params={"query": "test"}, confidence=0.9, reason=""),
            side_tools=[
                ToolBinding(name="read_file", params={"path": "/tmp"}, confidence=0.5, reason="check cache"),
                ToolBinding(name="grep", params={"pattern": "test"}, confidence=0.5, reason="search local"),
            ],
            retry_policy=RetryPolicy(max_retries=0, backoff=1.0),
        )

        result = asyncio.run(act_stage.execute(decision, situation))

        assert "web_search" in results
        assert "read_file" in results
        assert "grep" in results
        assert len(result.side_results) == 2

    # ── Evolution signals ──

    def test_evolution_signal_on_total_failure(self, act_stage, situation, tool_executor):
        """Complete failure (primary + fallback both fail) → evolution signal emitted."""
        tool_executor.execute = AsyncMock(side_effect=RuntimeError("everything broken"))

        decision = Decision(
            primary_tool=ToolBinding(name="web_search", params={"query": "test"}, confidence=0.9, reason=""),
            fallback_tool=ToolBinding(name="fetch_url", params={"url": ""}, confidence=0.5, reason="backup"),
            retry_policy=RetryPolicy(max_retries=0, backoff=1.0),
        )

        result = asyncio.run(act_stage.execute(decision, situation))

        assert result.success is False
        assert len(result.evolution_signals) > 0
        assert result.evolution_signals[0].type == "tool_failure"
        assert result.evolution_signals[0].tool == "web_search"

    # ── Circuit breaker integration ──

    def test_circuit_open_blocks_primary(self, act_stage, situation, mock_event_bus):
        """OPEN circuit → primary tool skipped, circuit_open signal emitted."""
        mock_event_bus.circuit_status = MagicMock(return_value="open")

        decision = Decision(
            primary_tool=ToolBinding(name="bash", params={"cmd": "ls"}, confidence=0.9, reason=""),
            fallback_tool=ToolBinding(name="web_search", params={"query": "ls"}, confidence=0.5, reason="backup"),
            retry_policy=RetryPolicy(max_retries=0, backoff=0.1),
        )

        result = asyncio.run(act_stage.execute(decision, situation))

        assert result.primary_error is not None
        assert "Circuit breaker open" in result.primary_error
        assert result.fallback_used is True
        assert result.fallback_tool == "web_search"
        # circuit_open signal emitted
        circuit_signals = [s for s in result.evolution_signals if s.type == "circuit_open"]
        assert len(circuit_signals) == 1
        assert circuit_signals[0].tool == "bash"

    def test_circuit_closed_allows_execution(self, act_stage, situation, mock_event_bus):
        """CLOSED circuit → normal execution, on_success called."""
        mock_event_bus.circuit_status = MagicMock(return_value="closed")

        decision = Decision(
            primary_tool=ToolBinding(name="bash", params={"cmd": "ls"}, confidence=0.9, reason=""),
            retry_policy=RetryPolicy(max_retries=0, backoff=0.1),
        )

        asyncio.run(act_stage.execute(decision, situation))

        mock_event_bus.circuit_on_success.assert_called_with("bash")
        mock_event_bus.circuit_on_failure.assert_not_called()

    def test_circuit_on_failure_called_after_primary_fails(self, act_stage, situation,
                                                            tool_executor, mock_event_bus):
        """Primary fails → circuit_on_failure called for that tool."""
        tool_executor.execute = AsyncMock(side_effect=[
            RuntimeError("primary boom"),
            "fallback ok",
        ])

        decision = Decision(
            primary_tool=ToolBinding(name="bash", params={}, confidence=0.9, reason=""),
            fallback_tool=ToolBinding(name="web_search", params={"query": "test"}, confidence=0.5, reason="backup"),
            retry_policy=RetryPolicy(max_retries=0, backoff=0.1),
        )

        asyncio.run(act_stage.execute(decision, situation))

        mock_event_bus.circuit_on_failure.assert_any_call("bash")
        # Fallback succeeded → its circuit gets on_success
        mock_event_bus.circuit_on_success.assert_any_call("web_search")

    def test_circuit_open_without_fallback_graceful(self, act_stage, situation, mock_event_bus):
        """Circuit OPEN with no fallback → graceful failure, no crash."""
        mock_event_bus.circuit_status = MagicMock(return_value="open")

        decision = Decision(
            primary_tool=ToolBinding(name="bash", params={}, confidence=0.9, reason=""),
            fallback_tool=None,
            retry_policy=RetryPolicy(max_retries=0, backoff=0.1),
        )

        result = asyncio.run(act_stage.execute(decision, situation))

        assert result.success is False
        assert result.primary_error is not None
        # circuit_open signal should be present, no tool_failure (no execution attempted)
        types = [s.type for s in result.evolution_signals]
        assert "circuit_open" in types

    # ── BID strategy ──

    def test_bid_strategy_executes_primary_and_fallback_concurrently(self, act_stage, situation, tool_executor):
        """BID strategy: primary and fallback execute concurrently, primary wins."""
        import time
        call_order = []

        async def slow_primary(name, params):
            call_order.append(name)
            await asyncio.sleep(0.05)
            return "primary result"

        async def fast_fallback(name, params):
            call_order.append(name)
            return "fallback result"

        tool_executor.execute = AsyncMock(side_effect=[RuntimeError("primary failed"), "fallback result"])

        decision = Decision(
            primary_tool=ToolBinding(name="web_search", params={"query": "test"}, confidence=0.9, reason=""),
            fallback_tool=ToolBinding(name="fetch_url", params={"url": ""}, confidence=0.5, reason="backup"),
            retry_policy=RetryPolicy(max_retries=0, backoff=1.0),
            strategy="BID",
        )

        result = asyncio.run(act_stage.execute(decision, situation))

        # Primary failed → fallback result used
        assert result.fallback_used is True
        assert result.fallback_tool == "fetch_url"
        assert result.fallback_result == "fallback result"

    def test_bid_strategy_cancels_fallback_when_primary_succeeds(self, act_stage, situation, tool_executor):
        """BID strategy: when primary succeeds, fallback task is cancelled."""
        tool_executor.execute = AsyncMock(side_effect=[
            "primary success",
            asyncio.CancelledError(),  # fallback gets cancelled
        ])

        decision = Decision(
            primary_tool=ToolBinding(name="web_search", params={"query": "test"}, confidence=0.9, reason=""),
            fallback_tool=ToolBinding(name="fetch_url", params={"url": ""}, confidence=0.5, reason="backup"),
            retry_policy=RetryPolicy(max_retries=0, backoff=1.0),
            strategy="BID",
        )

        result = asyncio.run(act_stage.execute(decision, situation))

        assert result.success is True
        assert result.primary_result == "primary success"
        assert result.fallback_used is False

    # ── PARALLEL strategy ──

    def test_parallel_strategy_executes_primary_and_side_tools_together(self, act_stage, situation, tool_executor):
        """PARALLEL strategy: primary and side tools run concurrently."""
        executed = []

        async def track(name, params):
            executed.append(name)
            return f"ok:{name}"

        tool_executor.execute = track

        decision = Decision(
            primary_tool=ToolBinding(name="web_search", params={"query": "test"}, confidence=0.9, reason=""),
            side_tools=[
                ToolBinding(name="read_file", params={"path": "/tmp"}, confidence=0.5, reason=""),
                ToolBinding(name="grep", params={"pattern": "x"}, confidence=0.5, reason=""),
            ],
            retry_policy=RetryPolicy(max_retries=0, backoff=1.0),
            strategy="PARALLEL",
        )

        result = asyncio.run(act_stage.execute(decision, situation))

        assert result.success is True
        assert result.primary_result == "ok:web_search"
        assert len(result.side_results) == 2
        assert "read_file" in result.side_results
        assert "grep" in result.side_results

    def test_parallel_strategy_fallback_on_primary_failure(self, act_stage, situation, tool_executor):
        """PARALLEL strategy: when primary fails, fallback is attempted."""
        tool_executor.execute = AsyncMock(side_effect=[
            RuntimeError("primary failed"),  # primary
            "side ok",                       # side tool
            "fallback result",               # fallback
        ])

        decision = Decision(
            primary_tool=ToolBinding(name="web_search", params={"query": "test"}, confidence=0.9, reason=""),
            side_tools=[
                ToolBinding(name="read_file", params={"path": "/tmp"}, confidence=0.5, reason=""),
            ],
            fallback_tool=ToolBinding(name="fetch_url", params={"url": ""}, confidence=0.5, reason="backup"),
            retry_policy=RetryPolicy(max_retries=0, backoff=1.0),
            strategy="PARALLEL",
        )

        result = asyncio.run(act_stage.execute(decision, situation))

        assert result.fallback_used is True
        assert result.fallback_tool == "fetch_url"
        assert result.fallback_result == "fallback result"
        assert len(result.side_results) == 1

    def test_parallel_strategy_side_tool_errors_are_captured(self, act_stage, situation, tool_executor):
        """PARALLEL strategy: side tool errors are captured, not fatal."""
        tool_executor.execute = AsyncMock(side_effect=[
            "primary ok",                   # primary
            RuntimeError("side tool boom"),  # side tool
        ])

        decision = Decision(
            primary_tool=ToolBinding(name="web_search", params={"query": "test"}, confidence=0.9, reason=""),
            side_tools=[
                ToolBinding(name="read_file", params={"path": "/tmp"}, confidence=0.5, reason=""),
            ],
            retry_policy=RetryPolicy(max_retries=0, backoff=1.0),
            strategy="PARALLEL",
        )

        result = asyncio.run(act_stage.execute(decision, situation))

        assert result.success is True
        assert result.primary_result == "primary ok"
        assert "read_file" in result.side_results
        assert "error" in result.side_results["read_file"]
