"""OODAEventBus — 封装 AsyncEventBus + CircuitBreaker 为 OODA Protocol."""
import asyncio
from unittest.mock import MagicMock, AsyncMock
import pytest

from seai.core.ooda.providers import EventBusProvider
from seai.core.ooda.event_bus import OODAEventBus


class TestOODAEventBus:
    @pytest.fixture
    def bus(self):
        return OODAEventBus()

    # ── Construction ──

    def test_implements_provider_protocol(self, bus):
        """OODAEventBus is an EventBusProvider."""
        assert isinstance(bus, EventBusProvider)

    def test_starts_with_empty_state(self, bus):
        """Fresh bus has no events and no circuits."""
        events, circuits = bus.snapshot()
        assert events == []
        assert circuits == {}

    # ── Publish and snapshot ──

    def test_publish_tool_event(self, bus):
        """Published tool events appear in snapshot."""
        asyncio.run(bus.publish_tool_started("web_search", {"query": "test"}))
        asyncio.run(bus.publish_tool_completed("web_search", "results found", 42))

        events, _ = bus.snapshot()
        assert len(events) >= 2
        event_types = [e.topic for e in events]
        assert "tool.started" in event_types
        assert "tool.completed" in event_types

    def test_publish_tool_failed(self, bus):
        """Tool failure events carry error info."""
        asyncio.run(bus.publish_tool_failed("bash", "permission denied"))

        events, _ = bus.snapshot()
        failures = [e for e in events if e.topic == "tool.failed"]
        assert len(failures) == 1
        assert failures[0].data["tool"] == "bash"
        assert "permission denied" in failures[0].data["error"]

    # ── Circuit breaker ──

    def test_circuit_tracks_tool_status(self, bus):
        """Circuit breaker state tracks tool success/failure."""
        bus.circuit_on_success("web_search")
        bus.circuit_on_success("web_search")
        bus.circuit_on_failure("web_search")

        _, circuits = bus.snapshot()
        assert "web_search" in circuits
        assert circuits["web_search"].state == "closed"
        assert circuits["web_search"].failures == 1

    def test_circuit_opens_after_repeated_failures(self, bus):
        """Circuit opens when failures exceed threshold."""
        for _ in range(6):
            bus.circuit_on_failure("bash")

        _, circuits = bus.snapshot()
        assert circuits["bash"].state == "open"
        assert circuits["bash"].failures >= 5

    def test_circuit_snapshot_includes_all_registered(self, bus):
        """Snapshot returns all registered circuit breakers."""
        bus.circuit_on_success("llm_call")
        bus.circuit_on_failure("tool_exec")

        _, circuits = bus.snapshot()
        assert "llm_call" in circuits
        assert "tool_exec" in circuits

    # ── Evolution signals subscription ──

    def test_subscribe_evolution_signal(self, bus):
        """Handlers can subscribe to evolution signals."""
        received = []

        async def handler(signal):
            received.append(signal)

        bus.subscribe_evolution(handler)

        asyncio.run(bus.publish_evolution_signal({
            "type": "tool_failure",
            "tool": "bash",
            "reason": "test",
            "severity": 0.9,
        }))

        assert len(received) == 1
        assert received[0]["type"] == "tool_failure"

    def test_multiple_evolution_subscribers(self, bus):
        """Multiple handlers can subscribe independently."""
        r1, r2 = [], []

        async def h1(s): r1.append(s)
        async def h2(s): r2.append(s)

        bus.subscribe_evolution(h1)
        bus.subscribe_evolution(h2)

        asyncio.run(bus.publish_evolution_signal({"type": "test"}))

        assert len(r1) == 1
        assert len(r2) == 1

    # ── History ──

    def test_history_respects_max_size(self, bus):
        """Event history is capped at max_size."""
        bus = OODAEventBus(max_history=3)
        for i in range(5):
            asyncio.run(bus.publish_tool_completed(f"tool_{i}", f"result_{i}", i))

        events, _ = bus.snapshot()
        assert len(events) <= 3 * 2  # Each completed publishes tool.completed event

    # ── Clear ──

    def test_clear_resets_all_state(self, bus):
        """clear() resets events and circuits."""
        asyncio.run(bus.publish_tool_completed("test", "ok", 1))
        bus.circuit_on_failure("test")

        bus.clear()

        events, circuits = bus.snapshot()
        assert events == []
        assert circuits == {}

    # ── Half-open state ──

    def test_half_open_transitions_to_closed_after_success_threshold(self, bus):
        """Circuit half_open → closed after enough consecutive successes."""
        from seai.core.ooda.types import CircuitConfig
        bus = OODAEventBus(default_circuit_config=CircuitConfig(
            failure_threshold=2,
            cooldown_s=0.0,  # immediate cooldown
            half_open_success_threshold=3,
        ))
        # Open the circuit (cooldown=0 means immediate transition to half_open)
        bus.circuit_on_failure("tool_a")
        bus.circuit_on_failure("tool_a")
        # After 2 failures with cooldown=0, circuit is already half_open
        assert bus.circuit_status("tool_a") == "half_open"

        # 3 successes in half_open → closed
        bus.circuit_on_success("tool_a")
        bus.circuit_on_success("tool_a")
        assert bus.circuit_status("tool_a") == "half_open"
        bus.circuit_on_success("tool_a")
        assert bus.circuit_status("tool_a") == "closed"

    def test_half_open_failure_reopens_circuit(self):
        """Failure during half_open → circuit reopens."""
        import time
        from seai.core.ooda.types import CircuitConfig
        bus = OODAEventBus(default_circuit_config=CircuitConfig(
            failure_threshold=2,
            cooldown_s=60.0,  # 60s cooldown — won't auto-transition in test
            half_open_success_threshold=3,
        ))
        bus.circuit_on_failure("tool_b")
        bus.circuit_on_failure("tool_b")
        assert bus.circuit_status("tool_b") == "open"

        # Manually force half_open (simulate cooldown elapsed)
        bus._circuits["tool_b"].state = "half_open"
        bus._circuits["tool_b"].half_open_count = 0
        assert bus.circuit_status("tool_b") == "half_open"

        # Failure during half_open → re-opens
        bus.circuit_on_failure("tool_b")
        assert bus.circuit_status("tool_b") == "open"

    def test_half_open_requires_cooldown(self, bus):
        """Circuit stays open until cooldown elapses."""
        from seai.core.ooda.types import CircuitConfig
        bus = OODAEventBus(default_circuit_config=CircuitConfig(
            failure_threshold=2, cooldown_s=3600.0,  # 1 hour cooldown
            half_open_success_threshold=3,
        ))
        bus.circuit_on_failure("tool_a")
        bus.circuit_on_failure("tool_a")
        assert bus.circuit_status("tool_a") == "open"

        # Still open — cooldown hasn't elapsed
        assert bus.circuit_status("tool_a") == "open"
