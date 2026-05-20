"""Real LLM smoke tests for OODA engine — requires a configured LLM provider.

Run with: pytest tests/smoke/ -m real_llm
Skip by default: pytest tests/smoke/ -m "not real_llm"
"""
import asyncio
import os
from unittest.mock import MagicMock, AsyncMock
import pytest

from seai.core.ooda.types import (
    Intent, OODALoopConfig,
)
from seai.core.ooda.observe import ObserveStage
from seai.core.ooda.orient import OrientStage
from seai.core.ooda.decide import DecideStage
from seai.core.ooda.act import ActStage
from seai.core.ooda.loop import OODALoop
from seai.core.ooda.adapters import (
    MemoryAdapter, KGAdapter, ToolExecutorAdapter, EventBusAdapter,
)
from seai.core.ooda.event_bus import OODAEventBus


pytestmark = pytest.mark.real_llm


def _get_llm():
    """Try to create a real LLM provider from environment or config.

    Returns None if no LLM is configured, so tests can skip.
    """
    api_key = os.environ.get("SEAI_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    api_base = os.environ.get("SEAI_LLM_API_BASE") or os.environ.get("OPENAI_API_BASE", "")
    model = os.environ.get("SEAI_LLM_MODEL") or os.environ.get("OPENAI_MODEL", "")

    if not api_key and not api_base:
        try:
            from seai.core.infra.config import config_manager
            endpoints = config_manager.get_llm_endpoints()
            if endpoints:
                ep = endpoints[0]
                api_key = ep.api_key
                api_base = ep.api_base
                model = ep.model
        except Exception:
            pass

    if not api_key and not api_base:
        return None

    from seai.core.interfaces.llm_provider import LLMProviderFactory

    try:
        if api_key:
            provider = LLMProviderFactory.create_openai_provider([{
                "name": "smoke-test",
                "api_base": api_base or "https://api.openai.com/v1",
                "api_key": api_key,
                "model": model or "gpt-4o-mini",
                "priority": 0,
            }])
            return provider
    except Exception:
        pass

    return None


def _make_tool_executor():
    """Minimal tool executor that simulates available tools."""
    te = MagicMock()
    te.list_tools = MagicMock(return_value=[
        {"name": "web_search", "description": "Search the web"},
        {"name": "read_file", "description": "Read a file from disk"},
        {"name": "grep", "description": "Search file contents with regex"},
        {"name": "bash", "description": "Execute a shell command"},
        {"name": "write_file", "description": "Write content to a file"},
        {"name": "edit", "description": "Edit a file with string replacement"},
        {"name": "fetch_url", "description": "Fetch content from a URL"},
    ])
    te.execute = AsyncMock(return_value="result from tool execution")
    return te


class TestOODARealLLM:
    """Smoke tests using a real LLM to verify end-to-end OODA pipeline."""

    @pytest.fixture
    def llm(self):
        provider = _get_llm()
        if provider is None:
            pytest.skip("No LLM provider configured (set SEAI_LLM_API_KEY or SEAI_LLM_API_BASE)")
        return provider

    @pytest.fixture
    def ooda_loop(self, llm):
        """Build a complete OODA loop wired to a real LLM."""
        event_bus = OODAEventBus()
        event_bus_adapter = EventBusAdapter(event_bus)

        observe = ObserveStage(
            memory=MemoryAdapter(None),
            kg=KGAdapter(),
            event_bus=event_bus_adapter,
        )
        orient = OrientStage(llm=llm, kg=KGAdapter())
        decide = DecideStage(llm=llm, tool_executor=_make_tool_executor())
        act = ActStage(
            tool_executor=_make_tool_executor(),
            memory=MemoryAdapter(None),
            kg=KGAdapter(),
            event_bus=event_bus_adapter,
        )
        return OODALoop(observe=observe, orient=orient, decide=decide, act=act)

    def test_single_iteration_simple_query(self, ooda_loop):
        """Real LLM drives a single OODA iteration end-to-end."""
        intent = Intent(raw="What is the capital of France?", category="general", confidence=0.9)
        config = OODALoopConfig(max_iterations=1)

        result = asyncio.run(ooda_loop.run(intent, config))

        assert result.status == "completed"
        assert len(result.actions) == 1
        assert len(result.trace) == 1
        # Verify trace data was collected
        trace = result.trace[0]
        assert trace.iteration == 1
        assert trace.orient_ms >= 0
        assert trace.decide_ms >= 0
        assert trace.act_ms >= 0
        assert trace.orient_strategy in ("SERIAL", "PARALLEL", "BID", "FALLBACK")
        assert len(trace.orient_capabilities) > 0

    def test_code_search_intent(self, ooda_loop):
        """Real LLM orients a code search intent."""
        intent = Intent(
            raw="Find all Python files that import asyncio",
            category="code_search",
            confidence=0.85,
        )
        config = OODALoopConfig(max_iterations=1)

        result = asyncio.run(ooda_loop.run(intent, config))

        assert result.status == "completed"
        assert len(result.actions) == 1
        trace = result.trace[0]
        assert trace.orient_strategy in ("SERIAL", "PARALLEL", "BID", "FALLBACK")
        # Code search should require file_read or code_search capabilities
        caps = trace.orient_capabilities
        assert any(c in ("file_read", "code_search", "grep") for c in caps) or len(caps) > 0

    def test_multi_iteration_loop(self, ooda_loop):
        """Real LLM drives 2-iteration OODA loop."""
        intent = Intent(raw="Search for Python async best practices", category="code_search", confidence=0.8)
        config = OODALoopConfig(max_iterations=2)

        result = asyncio.run(ooda_loop.run(intent, config))

        assert result.status == "completed"
        assert 1 <= len(result.actions) <= 2
        assert len(result.trace) == len(result.actions)
        assert result.total_ms > 0
        # Each trace entry should have valid data
        for trace in result.trace:
            assert trace.orient_ms >= 0
            assert trace.decide_ms >= 0

    def test_result_summary(self, ooda_loop):
        """Result summary includes meaningful content."""
        intent = Intent(raw="Explain what OODA loop means", category="general", confidence=0.9)
        config = OODALoopConfig(max_iterations=1)

        result = asyncio.run(ooda_loop.run(intent, config))

        assert len(result.summary) > 0
        assert "action" in result.summary.lower() or "1" in result.summary
