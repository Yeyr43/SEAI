"""OODAContext — runtime session context for OODA loop execution."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from seai.core.ooda.types import (
    SituationContext, Intent, ActionPlan, Decision, ToolBinding,
    RetryPolicy, ActionResult, EvolutionSignal, OODALoopConfig,
    TaskGoal,
)
from seai.core.ooda.providers import MemoryProvider, KGProvider, EventBusProvider
from seai.core.ooda.context import OODAContext


class TestOODAContextBuild:
    """Building initial context from raw input and providers."""

    @pytest.fixture
    def mock_memory(self):
        mem = MagicMock(spec=MemoryProvider)
        mem.search = AsyncMock(return_value=[])
        mem.get_profile = AsyncMock(return_value={"name": "test"})
        mem.get_session_summary = AsyncMock(return_value=None)
        return mem

    @pytest.fixture
    def mock_kg(self):
        kg = MagicMock(spec=KGProvider)
        kg.query = AsyncMock(return_value=[])
        return kg

    @pytest.fixture
    def mock_event_bus(self):
        bus = MagicMock(spec=EventBusProvider)
        bus.snapshot = MagicMock(return_value=([], {}))
        return bus

    @pytest.fixture
    def config(self):
        return OODALoopConfig(max_iterations=5)

    # ── Construction ──

    def test_build_from_intent(self, mock_memory, mock_kg, mock_event_bus, config):
        """Build OODAContext from an Intent object."""
        intent = Intent(raw="search for Python", category="code_search", confidence=0.9)
        ctx = OODAContext(
            intent=intent,
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
            config=config,
        )

        assert ctx.intent is intent
        assert ctx.situation is None  # Not yet gathered
        assert ctx.iteration == 0
        assert len(ctx.history) == 0
        assert ctx.config.max_iterations == 5

    def test_build_from_raw_string(self, mock_memory, mock_kg, mock_event_bus, config):
        """Build OODAContext from a raw string — creates an Intent automatically."""
        ctx = OODAContext(
            intent="find Rust async examples",
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
            config=config,
        )

        assert isinstance(ctx.intent, Intent)
        assert ctx.intent.raw == "find Rust async examples"
        assert ctx.intent.category == "general"
        assert ctx.intent.confidence == 0.5  # default for raw string

    def test_build_without_config_uses_defaults(self, mock_memory, mock_kg, mock_event_bus):
        """Config is optional — uses safe defaults."""
        ctx = OODAContext(
            intent=Intent(raw="test", category="test", confidence=0.8),
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
        )
        assert ctx.config.max_iterations == 10  # OODALoopConfig default

    # ── Gather (Observe delegation) ──

    def test_gather_builds_situation(self, mock_memory, mock_kg, mock_event_bus, config):
        """gather() queries providers and creates a SituationContext."""
        ctx = OODAContext(
            intent=Intent(raw="test", category="test", confidence=0.8),
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
            config=config,
        )
        situation = asyncio.run(ctx.gather())

        assert isinstance(situation, SituationContext)
        assert situation.intent == ctx.intent
        assert situation.turn_count == 1
        assert situation.user_profile == {"name": "test"}
        mock_memory.search.assert_awaited_once()
        mock_kg.query.assert_awaited_once()

    def test_gather_increments_turn_count(self, mock_memory, mock_kg, mock_event_bus, config):
        """Each gather() call increments turn_count."""
        ctx = OODAContext(
            intent=Intent(raw="test", category="test", confidence=0.8),
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
            config=config,
        )
        s1 = asyncio.run(ctx.gather())
        s2 = asyncio.run(ctx.gather())

        assert s1.turn_count == 1
        assert s2.turn_count == 2

    # ── Record keeping ──

    def test_record_iteration_tracks_history(self, mock_memory, mock_kg, mock_event_bus, config):
        """record_iteration stores plan/decision/result for later analysis."""
        ctx = OODAContext(
            intent=Intent(raw="test", category="test", confidence=0.8),
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
            config=config,
        )

        plan = ActionPlan(
            intent=ctx.intent,
            goal=TaskGoal(description="test goal"),
            strategy="SERIAL",
            required_capabilities=["web_search"],
            confidence=0.9,
        )
        decision = Decision(
            primary_tool=ToolBinding(name="web_search", params={"q": "test"}, confidence=0.9, reason="best"),
            retry_policy=RetryPolicy(max_retries=1, backoff=0.5),
        )
        result = ActionResult(
            success=True,
            primary_tool="web_search",
            primary_result="found stuff",
        )

        ctx.record_iteration(plan, decision, result)

        assert len(ctx.history) == 1
        entry = ctx.history[0]
        assert entry["plan"] is plan
        assert entry["decision"] is decision
        assert entry["result"] is result
        assert ctx.iteration == 1
        assert ctx.last_result is result

    # ── Evolution tracking ──

    def test_evolution_signals_accumulate(self, mock_memory, mock_kg, mock_event_bus):
        """Evolution signals from multiple iterations are accumulated."""
        config = OODALoopConfig(max_iterations=5, evolution_check_interval=1)
        ctx = OODAContext(
            intent=Intent(raw="test", category="test", confidence=0.8),
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
            config=config,
        )

        r1 = ActionResult(
            success=False,
            primary_tool="bash",
            primary_error="failed",
            evolution_signals=[EvolutionSignal(type="tool_failure", tool="bash", reason="fail", severity=0.8)],
        )
        r2 = ActionResult(
            success=False,
            primary_tool="bash",
            primary_error="failed again",
            evolution_signals=[EvolutionSignal(type="tool_failure", tool="bash", reason="fail again", severity=0.9)],
        )

        ctx.record_iteration(None, None, r1)
        ctx.record_iteration(None, None, r2)

        assert len(ctx.evolution_signals) == 2
        assert ctx.should_trigger_evolution() is True  # 2 failures >= check_interval(1)

    def test_no_evolution_when_succeeding(self, mock_memory, mock_kg, mock_event_bus, config):
        """Successful iterations don't trigger evolution."""
        ctx = OODAContext(
            intent=Intent(raw="test", category="test", confidence=0.8),
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
            config=config,
        )

        r = ActionResult(success=True, primary_tool="web_search", primary_result="ok")
        ctx.record_iteration(None, None, r)

        assert ctx.should_trigger_evolution() is False

    # ── Context exhaustion ──

    def test_context_exhaustion_check(self, mock_memory, mock_kg, mock_event_bus):
        """Detects when context window is exhausted."""
        config = OODALoopConfig(context_critical_ratio=0.7)
        ctx = OODAContext(
            intent=Intent(raw="test", category="test", confidence=0.8),
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
            config=config,
        )

        ctx._current_usage_ratio = 0.85  # Simulate high usage
        assert ctx.is_context_exhausted() is True

        ctx._current_usage_ratio = 0.3
        assert ctx.is_context_exhausted() is False

    # ── Summary ──

    def test_build_summary(self, mock_memory, mock_kg, mock_event_bus, config):
        """build_summary produces a human-readable loop summary."""
        ctx = OODAContext(
            intent=Intent(raw="search Python docs", category="code_search", confidence=0.9),
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
            config=config,
        )

        ctx.record_iteration(
            None,
            Decision(primary_tool=ToolBinding(name="web_search", params={}, confidence=0.9, reason="")),
            ActionResult(success=True, primary_tool="web_search", primary_result="Python 3.14 docs"),
        )

        summary = ctx.build_summary()
        assert "Python" in summary
        assert "web_search" in summary
