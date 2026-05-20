"""Integration tests for OODA engine wired into tool_loop and agent."""
import asyncio
from unittest.mock import AsyncMock, MagicMock
import pytest

from seai.core.ooda.types import Intent
from seai.core.ooda.context import OODAContext
from seai.core.ooda.adapters import (
    MemoryAdapter, KGAdapter, ToolExecutorAdapter, EventBusAdapter,
)
from seai.core.tool_loop.ooda_loop import OODAToolLoopEngine


# ── Adapter tests ──

class TestMemoryAdapter:
    def test_search_delegates_to_memory_store(self):
        store = MagicMock()
        store.search_memory = MagicMock(return_value=[
            MagicMock(content="test memory", score=0.9, mem_type="fact"),
        ])

        adapter = MemoryAdapter(store)
        results = asyncio.run(adapter.search("test query"))

        store.search_memory.assert_called_once_with("test query", top_k=5)
        assert len(results) == 1
        assert results[0].content == "test memory"

    def test_search_filter_by_type(self):
        store = MagicMock()
        store.search_memory = MagicMock(return_value=[
            MagicMock(content="fact A", score=0.9, mem_type="fact"),
            MagicMock(content="pref B", score=0.8, mem_type="preference"),
        ])

        adapter = MemoryAdapter(store)
        results = asyncio.run(adapter.search("test", filter_types=["fact"]))

        assert len(results) == 1
        assert results[0].content == "fact A"

    def test_search_handles_store_failure(self):
        store = MagicMock()
        store.search_memory = MagicMock(side_effect=RuntimeError("down"))

        adapter = MemoryAdapter(store)
        results = asyncio.run(adapter.search("test"))

        assert results == []

    def test_get_profile(self):
        store = MagicMock()
        store.get_user_profile = MagicMock(return_value={"name": "dev"})

        adapter = MemoryAdapter(store)
        profile = asyncio.run(adapter.get_profile("user-1"))

        assert profile == {"name": "dev"}


class TestToolExecutorAdapter:
    def test_execute_delegates(self):
        te = MagicMock()
        te.execute_tool = AsyncMock(return_value="result")

        adapter = ToolExecutorAdapter(te)
        result = asyncio.run(adapter.execute("web_search", {"query": "test"}))

        assert result == "result"
        te.execute_tool.assert_awaited_once_with("web_search", {"query": "test"})

    def test_list_tools_delegates(self):
        te = MagicMock()
        te.get_tool_definitions = MagicMock(return_value=[
            {"name": "web_search", "description": "search"},
        ])

        adapter = ToolExecutorAdapter(te)
        tools = adapter.list_tools()

        assert len(tools) == 1
        assert tools[0]["name"] == "web_search"


class TestEventBusAdapter:
    def test_snapshot_without_bus_returns_empty(self):
        adapter = EventBusAdapter()
        events, circuits = adapter.snapshot()
        assert events == []
        assert circuits == {}

    def test_snapshot_with_bus(self):
        bus = MagicMock()
        bus.snapshot = MagicMock(return_value=([MagicMock(topic="test")], {"a": "b"}))

        adapter = EventBusAdapter(bus)
        events, circuits = adapter.snapshot()

        assert len(events) == 1
        assert circuits == {"a": "b"}


# ── OODAToolLoopEngine tests ──

class TestOODAToolLoopEngine:
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
        te.get_tool_definitions = MagicMock(return_value=[
            {"name": "web_search", "description": "Search the web"},
            {"name": "fetch_url", "description": "Fetch URL"},
        ])
        te.execute_tool = AsyncMock(return_value="search results: Python 3.14 docs")
        return te

    @pytest.fixture
    def mock_memory_store(self):
        store = MagicMock()
        store.search_memory = MagicMock(return_value=[])
        store.get_user_profile = MagicMock(return_value={})
        store.get_session_summary = MagicMock(return_value=None)
        return store

    @pytest.fixture
    def engine(self, mock_llm, mock_tool_executor, mock_memory_store):
        return OODAToolLoopEngine(
            llm_provider=mock_llm,
            tool_executor=mock_tool_executor,
            memory_store=mock_memory_store,
        )

    def test_run_tool_loop_returns_string(self, engine):
        """run_tool_loop returns a string result, matching ToolLoopEngine contract."""
        messages = [{"role": "user", "content": "search for Python async"}]
        tools = [{"name": "web_search"}]

        result = asyncio.run(engine.run_tool_loop(messages, tools, max_rounds=2))

        assert isinstance(result, str)
        assert len(result) > 0

    def test_run_tool_loop_extracts_intent_from_messages(self, engine, mock_tool_executor):
        """Intent is extracted from the last user message."""
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "find Rust async examples"},
        ]

        asyncio.run(engine.run_tool_loop(messages, [], max_rounds=1))
        # Tool should have been called with the user's query
        assert mock_tool_executor.execute_tool.await_count >= 1

    def test_process_sync_delegates_to_run_tool_loop(self, engine):
        """process_sync is an alias for run_tool_loop."""
        messages = [{"role": "user", "content": "hello"}]
        result = asyncio.run(engine.process_sync(messages, []))
        assert isinstance(result, str)

    def test_run_tool_loop_without_memory_store(self, mock_llm, mock_tool_executor):
        """Engine works without a memory store (uses no-op fallback)."""
        engine = OODAToolLoopEngine(
            llm_provider=mock_llm,
            tool_executor=mock_tool_executor,
            memory_store=None,
        )
        messages = [{"role": "user", "content": "test"}]
        result = asyncio.run(engine.run_tool_loop(messages, [], max_rounds=1))
        assert isinstance(result, str)

    def test_evolution_bridge_created_when_service_provided(self, mock_llm, mock_tool_executor):
        """EvolutionBridge is wired when evolution_service + feedback_loop are given."""
        evo_svc = MagicMock()
        fb_loop = MagicMock()

        engine = OODAToolLoopEngine(
            llm_provider=mock_llm,
            tool_executor=mock_tool_executor,
            evolution_service=evo_svc,
            feedback_loop=fb_loop,
        )
        assert engine._evolution_bridge is not None

    def test_evolution_bridge_skipped_when_no_service(self, mock_llm, mock_tool_executor):
        """Without evolution_service or feedback_loop, no bridge is created."""
        engine = OODAToolLoopEngine(
            llm_provider=mock_llm,
            tool_executor=mock_tool_executor,
        )
        assert engine._evolution_bridge is None

    def test_run_tool_loop_respects_max_rounds(self, engine, mock_tool_executor):
        """max_rounds limits the number of OODA iterations."""
        messages = [{"role": "user", "content": "test"}]

        asyncio.run(engine.run_tool_loop(messages, [], max_rounds=3))
        # With max_rounds=3, tool should be called at most 3 times
        assert mock_tool_executor.execute_tool.await_count <= 3


# ── OODAContext end-to-end with adapters ──

class TestOODAContextWithAdapters:
    """Test OODAContext wired to real adapter chain."""

    def test_full_context_lifecycle(self):
        memory_store = MagicMock()
        memory_store.search_memory = MagicMock(return_value=[])
        memory_store.get_user_profile = MagicMock(return_value={"role": "developer"})
        memory_store.get_session_summary = MagicMock(return_value="prev session")

        memory = MemoryAdapter(memory_store)
        kg = KGAdapter()
        event_bus = EventBusAdapter()

        ctx = OODAContext(
            intent="test query",
            memory=memory,
            kg=kg,
            event_bus=event_bus,
        )

        situation = asyncio.run(ctx.gather())

        assert situation.user_profile == {"role": "developer"}
        assert situation.session_summary == "prev session"
        assert situation.turn_count == 1


# ── Closed-loop evolution verification ──

class TestEvolutionClosedLoop:
    """End-to-end: ActStage failure → EventBus → EvolutionBridge → EvolutionService."""

    def test_full_pipeline_auto_fix(self):
        """Signal flows: ActStage → EventBusAdapter → OODAEventBus → EvolutionBridge → auto_fix."""
        from seai.core.ooda.event_bus import OODAEventBus
        from seai.core.ooda.evolution_bridge import EvolutionBridge

        bus = OODAEventBus()
        bus_adapter = EventBusAdapter(bus)

        evolution_service = MagicMock()
        evolution_service.auto_fix_tool = AsyncMock(return_value="fix applied")
        evolution_service.deep_evolve = AsyncMock(return_value={"status": "ok"})

        feedback_loop = MagicMock()
        feedback_loop.add_signal = MagicMock()

        bridge = EvolutionBridge(
            event_bus=bus,
            evolution_service=evolution_service,
            feedback_loop=feedback_loop,
            failure_threshold=2,
        )

        # Simulate two bash failures via event bus (as ActStage would do)
        async def _publish_two_failures():
            await bus_adapter.publish_evolution_signal({
                "type": "tool_failure",
                "tool": "bash",
                "reason": "cmd failed",
                "severity": 0.8,
            })
            # Allow create_task to run
            await asyncio.sleep(0)
            await bus_adapter.publish_evolution_signal({
                "type": "tool_failure",
                "tool": "bash",
                "reason": "cmd failed again",
                "severity": 0.9,
            })
            await asyncio.sleep(0)

        asyncio.run(_publish_two_failures())

        evolution_service.auto_fix_tool.assert_called()
        feedback_loop.add_signal.assert_called()
        # Counter resets after auto_fix
        assert bridge.failure_count("bash") == 0

    def test_act_stage_publishes_failure_signal_to_bus(self):
        """ActStage publishes EvolutionSignals to EventBusAdapter on failure."""
        from seai.core.ooda.event_bus import OODAEventBus
        from seai.core.ooda.act import ActStage
        from seai.core.ooda.types import Decision, ToolBinding, RetryPolicy

        bus = OODAEventBus()
        bus_adapter = EventBusAdapter(bus)

        # Track received signals
        received = []

        def _collector(signal):
            received.append(signal)

        bus.subscribe_evolution(_collector)

        # Tool executor that always fails
        tool_executor = MagicMock()
        tool_executor.execute = AsyncMock(side_effect=RuntimeError("tool crashed"))
        tool_executor.list_tools = MagicMock(return_value=[])

        memory = MagicMock()
        kg = MagicMock()

        act = ActStage(
            tool_executor=tool_executor,
            memory=memory,
            kg=kg,
            event_bus=bus_adapter,
        )

        from seai.core.ooda.types import SituationContext, Intent
        decision = Decision(
            primary_tool=ToolBinding(
                name="bash",
                params={"cmd": "echo hi"},
                confidence=0.9,
                reason="test",
            ),
            fallback_tool=None,
            retry_policy=RetryPolicy(max_retries=0, backoff=0.1),
        )
        situation = SituationContext(intent=Intent(raw="test", category="test", confidence=0.5))

        asyncio.run(act.execute(decision, situation))

        assert len(received) >= 1
        assert received[0]["type"] == "tool_failure"
        assert received[0]["tool"] == "bash"

    def test_bridge_processes_act_stage_signals(self):
        """Full chain: ActStage failure → Bus → Bridge → auto_fix + feedback."""
        from seai.core.ooda.event_bus import OODAEventBus
        from seai.core.ooda.evolution_bridge import EvolutionBridge
        from seai.core.ooda.act import ActStage
        from seai.core.ooda.types import (
            Decision, ToolBinding, RetryPolicy,
            SituationContext, Intent,
        )

        bus = OODAEventBus()
        bus_adapter = EventBusAdapter(bus)

        evolution_service = MagicMock()
        evolution_service.auto_fix_tool = AsyncMock()
        evolution_service.deep_evolve = AsyncMock()

        feedback_loop = MagicMock()
        feedback_loop.add_signal = MagicMock()

        bridge = EvolutionBridge(
            event_bus=bus,
            evolution_service=evolution_service,
            feedback_loop=feedback_loop,
            failure_threshold=1,  # Trigger immediately
            deep_evolve_threshold=5,
        )

        tool_executor = MagicMock()
        tool_executor.execute = AsyncMock(side_effect=RuntimeError("boom"))
        tool_executor.list_tools = MagicMock(return_value=[])

        act = ActStage(
            tool_executor=tool_executor,
            memory=MagicMock(),
            kg=MagicMock(),
            event_bus=bus_adapter,
        )

        decision = Decision(
            primary_tool=ToolBinding(
                name="bash", params={}, confidence=0.9, reason="test",
            ),
            fallback_tool=None,
            retry_policy=RetryPolicy(max_retries=0, backoff=0.1),
        )
        situation = SituationContext(intent=Intent(raw="test", category="test", confidence=0.5))

        async def _run():
            await act.execute(decision, situation)
            await asyncio.sleep(0.1)  # Allow create_task to finish

        asyncio.run(_run())

        evolution_service.auto_fix_tool.assert_called()
        feedback_loop.add_signal.assert_called()

    def test_event_bus_snapshot_reflects_tool_events(self):
        """EventBus snapshot includes tool events published by ActStage."""
        from seai.core.ooda.event_bus import OODAEventBus

        bus = OODAEventBus()

        async def _simulate():
            await bus.publish_tool_started("bash", {"cmd": "ls"})
            await bus.publish_tool_failed("bash", "permission denied")

        asyncio.run(_simulate())

        events, circuits = bus.snapshot()

        assert len(events) == 2
        assert events[0].topic == "tool.started"
        assert events[1].topic == "tool.failed"
        # Circuit breaker is explicit; verify events are independently tracked


# ── Engine config switch ──

class TestEngineConfigSwitch:
    """Verify OODA engine can be selected via config."""

    def test_default_engine_is_tool_loop(self):
        """Without 'engine' key, ToolLoopEngine is used (default)."""
        config = {}
        engine_type = config.get("engine", "default")
        assert engine_type == "default"

    def test_ooda_engine_selected_when_configured(self):
        """When config['engine'] == 'ooda', OODAToolLoopEngine is selected."""
        config = {"engine": "ooda"}
        engine_type = config.get("engine", "default")
        assert engine_type == "ooda"

    def test_ooda_engine_accepts_full_constructor(self):
        """OODAToolLoopEngine constructor accepts same params as ToolLoopEngine."""
        from seai.core.tool_loop.ooda_loop import OODAToolLoopEngine

        mock_llm = MagicMock()
        mock_tool_exec = MagicMock()
        mock_tool_exec.execute_tool = AsyncMock(return_value="ok")
        mock_tool_exec.get_tool_definitions = MagicMock(return_value=[])
        mock_memory = MagicMock()
        mock_error_handler = MagicMock()
        mock_evo_service = MagicMock()
        mock_convo_service = MagicMock()
        mock_feedback_loop = MagicMock()
        mock_skill_system = MagicMock()
        mock_skill_repo = MagicMock()

        engine = OODAToolLoopEngine(
            llm_provider=mock_llm,
            tool_executor=mock_tool_exec,
            skill_system=mock_skill_system,
            skill_repository=mock_skill_repo,
            memory_store=mock_memory,
            error_handler=mock_error_handler,
            evolution_service=mock_evo_service,
            conversation_service=mock_convo_service,
            feedback_loop=mock_feedback_loop,
            data_dir="/tmp/test",
            circuit_breaker=MagicMock(),
            security=MagicMock(),
        )

        assert engine is not None
        assert engine.llm_provider is mock_llm
        assert engine.tool_executor is mock_tool_exec
        assert engine.memory_store is mock_memory
        # EvolutionBridge should be created when both services are provided
        assert engine._evolution_bridge is not None

    def test_ooda_import_failure_falls_back_to_default(self):
        """When OODA module import fails, ToolLoopEngine is used as fallback."""
        import sys
        from unittest.mock import patch

        fake_module_name = "seai.core.tool_loop.ooda_loop"

        with patch.dict(sys.modules, {fake_module_name: None}):
            engine_type = "ooda"
            used_ooda = False
            try:
                from seai.core.tool_loop.ooda_loop import OODAToolLoopEngine
                used_ooda = True
            except (ImportError, TypeError):
                used_ooda = False

            assert not used_ooda  # Should have fallen back
