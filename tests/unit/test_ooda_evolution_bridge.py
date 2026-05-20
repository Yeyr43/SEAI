"""EvolutionBridge — OODA EvolutionSignal → EvolutionService + FeedbackLoop."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from seai.core.ooda.types import EvolutionSignal
from seai.core.ooda.event_bus import OODAEventBus
from seai.core.ooda.evolution_bridge import EvolutionBridge


class TestEvolutionBridge:
    @pytest.fixture
    def mock_evolution_service(self):
        svc = MagicMock()
        svc.auto_fix_tool = AsyncMock(return_value="fix applied")
        svc.deep_evolve = AsyncMock(return_value={"status": "ok"})
        return svc

    @pytest.fixture
    def mock_feedback_loop(self):
        loop = MagicMock()
        loop.add_signal = MagicMock()
        return loop

    @pytest.fixture
    def event_bus(self):
        return OODAEventBus()

    @pytest.fixture
    def bridge(self, event_bus, mock_evolution_service, mock_feedback_loop):
        return EvolutionBridge(
            event_bus=event_bus,
            evolution_service=mock_evolution_service,
            feedback_loop=mock_feedback_loop,
            failure_threshold=2,
        )

    # ── Signal accumulation ──

    def test_accumulates_signals_per_tool(self, bridge):
        """Signals are counted per tool (below threshold, no reset)."""
        s1 = EvolutionSignal(type="tool_failure", tool="bash", reason="err", severity=0.8)
        s2 = EvolutionSignal(type="tool_failure", tool="web_search", reason="err", severity=0.5)

        asyncio.run(bridge.process_signals([s1, s2]))

        assert bridge.failure_count("bash") == 1
        assert bridge.failure_count("web_search") == 1

    def test_empty_signals_no_effect(self, bridge):
        """Empty signal list is a no-op."""
        asyncio.run(bridge.process_signals([]))
        assert bridge.total_failures == 0

    # ── Auto-fix trigger ──

    def test_triggers_auto_fix_at_threshold(self, bridge, mock_evolution_service):
        """When failures cross threshold, auto_fix_tool is called."""
        signals = [
            EvolutionSignal(type="tool_failure", tool="bash", reason="e1", severity=0.8),
            EvolutionSignal(type="tool_failure", tool="bash", reason="e2", severity=0.9),
        ]

        asyncio.run(bridge.process_signals(signals))

        mock_evolution_service.auto_fix_tool.assert_awaited_once_with(
            "bash", "e2", {}
        )

    def test_resets_counter_after_auto_fix(self, bridge):
        """After auto-fix, failure counter resets for that tool."""
        signals = [
            EvolutionSignal(type="tool_failure", tool="bash", reason="e1", severity=0.8),
            EvolutionSignal(type="tool_failure", tool="bash", reason="e2", severity=0.9),
        ]

        asyncio.run(bridge.process_signals(signals))

        assert bridge.failure_count("bash") == 0

    def test_wont_trigger_below_threshold(self, bridge, mock_evolution_service):
        """Single failure doesn't trigger auto_fix."""
        signals = [
            EvolutionSignal(type="tool_failure", tool="bash", reason="e1", severity=0.8),
        ]

        asyncio.run(bridge.process_signals(signals))

        mock_evolution_service.auto_fix_tool.assert_not_called()

    # ── Deep evolve trigger ──

    def test_triggers_deep_evolve_on_high_severity(self, bridge, mock_evolution_service):
        """High severity signals trigger deep_evolve."""
        signals = [
            EvolutionSignal(type="tool_failure", tool="bash", reason="critical", severity=1.0),
            EvolutionSignal(type="tool_failure", tool="web_search", reason="fail", severity=0.9),
        ]

        asyncio.run(bridge.process_signals(signals))

        # Severity 1.0 >= 0.95 triggers deep_evolve
        assert bridge.total_failures == 2
        mock_evolution_service.deep_evolve.assert_called()

    # ── FeedbackLoop integration ──

    def test_forwards_to_feedback_loop(self, bridge, mock_feedback_loop):
        """Signals are forwarded to FeedbackLoop."""
        signals = [
            EvolutionSignal(type="tool_failure", tool="web_search", reason="timeout", severity=0.6),
        ]

        asyncio.run(bridge.process_signals(signals))

        mock_feedback_loop.add_signal.assert_called()

    # ── Full integration: signals via EventBus ──

    def test_subscribes_to_event_bus(self, bridge, event_bus):
        """Bridge receives signals published on event bus."""
        sig_dict = {
            "type": "tool_failure",
            "tool": "grep",
            "reason": "not found",
            "severity": 0.7,
        }

        async def _publish_and_wait():
            await event_bus.publish_evolution_signal(sig_dict)
            # Allow create_task to run
            await asyncio.sleep(0)

        asyncio.run(_publish_and_wait())

        assert bridge.failure_count("grep") == 1
