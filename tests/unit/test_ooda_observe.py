"""Observe stage: gathers situation context from Memory, KG, and EventBus providers."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from seai.core.ooda.types import SituationContext, Intent
from seai.core.ooda.providers import MemoryProvider, KGProvider, EventBusProvider
from seai.core.ooda.observe import ObserveStage


class TestObserveStage:
    """Observe stage tests — no LLM dependency (pure unit tests)."""

    @pytest.fixture
    def mock_memory(self):
        mem = MagicMock(spec=MemoryProvider)
        mem.search = AsyncMock(return_value=[
            MagicMock(content="user prefers short answers", score=0.9, mem_type="preference"),
            MagicMock(content="last session was about Rust", score=0.7, mem_type="session"),
        ])
        mem.get_profile = AsyncMock(return_value={"name": "test-user", "locale": "zh-CN"})
        mem.get_session_summary = AsyncMock(return_value="Previous session discussed Rust acceleration.")
        return mem

    @pytest.fixture
    def mock_kg(self):
        kg = MagicMock(spec=KGProvider)
        kg.query = AsyncMock(return_value=[
            MagicMock(entity="Rust", relation="used_in", target="SEAI", confidence=0.95),
            MagicMock(entity="Python", relation="hosts", target="Rust", confidence=0.8),
        ])
        return kg

    @pytest.fixture
    def mock_event_bus(self):
        bus = MagicMock(spec=EventBusProvider)
        bus.snapshot = MagicMock(return_value=(
            [MagicMock(topic="tool.completed", data={"tool": "grep"}, ts=1234567890)],
            {"llm_call": MagicMock(state="closed", failures=0)},
        ))
        return bus

    @pytest.fixture
    def observe_stage(self, mock_memory, mock_kg, mock_event_bus):
        return ObserveStage(
            memory=mock_memory,
            kg=mock_kg,
            event_bus=mock_event_bus,
        )

    def async_test(self, coro):
        return asyncio.run(coro)

    # ── Tracer bullet: basic gather ──

    def test_gather_populates_situation_context(self, observe_stage):
        """Gather produces a SituationContext with all fields populated."""
        intent = Intent(raw="find Rust code", category="code_search", confidence=0.9)
        context = self.async_test(observe_stage.gather(
            intent=intent, session_id="sess-001",
        ))

        assert isinstance(context, SituationContext)
        assert context.intent == intent
        assert len(context.related_memories) == 2
        assert len(context.related_knowledge) == 2
        assert len(context.recent_events) == 1
        assert context.user_profile["locale"] == "zh-CN"
        assert context.session_summary is not None
        assert context.turn_count == 0

    # ── Graceful degradation ──

    def test_gather_handles_memory_failure_gracefully(self, mock_kg, mock_event_bus):
        """If MemoryProvider.search raises, Observe still returns a valid context."""
        bad_memory = MagicMock(spec=MemoryProvider)
        bad_memory.search = AsyncMock(side_effect=RuntimeError("memory down"))
        bad_memory.get_profile = AsyncMock(return_value={})
        bad_memory.get_session_summary = AsyncMock(return_value=None)

        stage = ObserveStage(memory=bad_memory, kg=mock_kg, event_bus=mock_event_bus)
        intent = Intent(raw="test", category="test", confidence=1.0)
        context = self.async_test(stage.gather(intent=intent, session_id="sess-002"))

        assert isinstance(context, SituationContext)
        assert context.related_memories == []  # degraded gracefully
        assert len(context.related_knowledge) == 2  # unaffected

    def test_gather_handles_kg_failure_gracefully(self, mock_memory, mock_event_bus):
        """If KGProvider.query raises, Observe still returns a valid context."""
        bad_kg = MagicMock(spec=KGProvider)
        bad_kg.query = AsyncMock(side_effect=RuntimeError("kg down"))

        stage = ObserveStage(memory=mock_memory, kg=bad_kg, event_bus=mock_event_bus)
        intent = Intent(raw="test", category="test", confidence=1.0)
        context = self.async_test(stage.gather(intent=intent, session_id="sess-003"))

        assert isinstance(context, SituationContext)
        assert len(context.related_knowledge) == 0  # degraded gracefully
        assert len(context.related_memories) == 2  # unaffected

    # ── Parallel execution ──

    def test_gather_queries_all_sources(self, observe_stage, mock_memory, mock_kg, mock_event_bus):
        """Observe queries Memory, KG, and EventBus — all three calls happen."""
        intent = Intent(raw="test", category="test", confidence=1.0)
        self.async_test(observe_stage.gather(intent=intent, session_id="sess-004"))

        mock_memory.search.assert_awaited_once()
        mock_kg.query.assert_awaited_once()
        mock_event_bus.snapshot.assert_called_once()
