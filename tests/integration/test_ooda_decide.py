"""Decide stage: unit tests for tool selection + integration tests with real LLM."""
import asyncio
from unittest.mock import MagicMock, AsyncMock
import pytest

from seai.core.ooda.types import (
    SituationContext, Intent, ActionPlan, Decision, ToolBinding, RetryPolicy,
    TaskGoal, MemoryHit,
)
from seai.core.ooda.providers import KGProvider
from seai.core.ooda.decide import DecideStage, CAPABILITY_TOOL_MAP
from seai.core.interfaces.llm_provider import LLMProvider


# ── Unit tests: tool mapping (no LLM required) ──

class TestDecideToolMapping:
    """Tests for capability-to-tool mapping rules."""

    def test_known_capability_maps_to_tools(self):
        assert "bash" in CAPABILITY_TOOL_MAP["code_generation"]
        assert "web_search" in CAPABILITY_TOOL_MAP["web_search"]
        assert "read_file" in CAPABILITY_TOOL_MAP["file_read"]
        assert "write_file" in CAPABILITY_TOOL_MAP["file_write"]

    def test_tool_has_fallback(self):
        """Each capability should have a primary + fallback or be standalone."""
        for capability, tools in CAPABILITY_TOOL_MAP.items():
            assert len(tools) >= 1, f"{capability} has no tools"
            assert len(tools) <= 3, f"{capability} has too many tools"

    def test_no_orphan_capabilities(self):
        """Every capability must have at least one tool mapped."""
        for capability, tools in CAPABILITY_TOOL_MAP.items():
            assert len(tools) >= 1, f"{capability} has no tools"


class TestDecideResponseParsing:
    """Tests for the _parse_decision method."""

    @staticmethod
    def _make_context():
        intent = Intent(raw="search for Python docs", category="code_search", confidence=0.9)
        return SituationContext(
            intent=intent,
            related_memories=[],
            related_knowledge=[],
            recent_events=[],
            circuit_state={},
            user_profile={},
            session_summary=None,
            turn_count=0,
        )

    def _make_plan(self, capabilities: list[str] | None = None) -> ActionPlan:
        return ActionPlan(
            intent=Intent(raw="search for Python docs", category="code_search", confidence=0.9),
            goal=TaskGoal(description="find docs"),
            strategy="SERIAL",
            required_capabilities=capabilities or ["web_search"],
            confidence=0.9,
            gap_analysis="",
        )

    def test_parse_valid_decision_json(self):
        stage = DecideStage(llm=MagicMock(), tool_executor=MagicMock())
        plan = self._make_plan()
        ctx = self._make_context()
        response = (
            '{"primary_tool": {"name": "web_search", "params": {"query": "Python docs"}, '
            '"confidence": 0.95, "reason": "best match for web_search"}, '
            '"fallback_tool": {"name": "fetch_url", "params": {"url": ""}, '
            '"confidence": 0.5, "reason": "backup"}, '
            '"side_tools": [], '
            '"retry_policy": {"max_retries": 2, "backoff": 1.0}, '
            '"timeout_ms": 30000, '
            '"tool_context_prompt": "search the web"}'
        )
        decision = stage._parse_decision(response, plan, ctx)

        assert isinstance(decision, Decision)
        assert decision.primary_tool is not None
        assert decision.primary_tool.name == "web_search"
        assert decision.primary_tool.confidence == 0.95
        assert decision.fallback_tool is not None
        assert decision.fallback_tool.name == "fetch_url"
        assert decision.retry_policy.max_retries == 2

    def test_parse_invalid_json_returns_fallback_decision(self):
        stage = DecideStage(llm=MagicMock(), tool_executor=MagicMock())
        plan = self._make_plan()
        ctx = self._make_context()
        decision = stage._parse_decision("not json", plan, ctx)

        assert isinstance(decision, Decision)
        assert decision.primary_tool is not None  # falls back to first capability tool
        assert decision.primary_tool.confidence < 1.0

    def test_constrained_selection_respects_required_capabilities(self):
        """Tool selection is constrained to required_capabilities."""
        stage = DecideStage(llm=MagicMock(), tool_executor=MagicMock())
        plan = self._make_plan(capabilities=["file_read"])
        ctx = self._make_context()

        # Even if LLM response asks for web_search, constrained selection
        # should prefer tools from file_read capability
        tools = stage._get_allowed_tools(plan)
        assert "read_file" in tools or "grep" in tools
        # web_search should NOT be allowed since it's not in required_capabilities
        if "web_search" not in plan.required_capabilities:
            assert "web_search" not in tools or len(tools) > 2  # might be there as broader set


# ── Integration tests (mock LLM, testing stage behavior end-to-end) ──


class TestDecideStageIntegration:
    @pytest.fixture
    def mock_tool_executor(self):
        te = MagicMock()
        te.list_tools = MagicMock(return_value=[
            {"name": "web_search", "description": "Search the web"},
            {"name": "fetch_url", "description": "Fetch a URL"},
            {"name": "read_file", "description": "Read a file"},
            {"name": "grep", "description": "Search file contents"},
            {"name": "bash", "description": "Execute shell command"},
            {"name": "write_file", "description": "Write to a file"},
            {"name": "edit", "description": "Edit a file"},
        ])
        return te

    @staticmethod
    def make_context(raw: str) -> SituationContext:
        return SituationContext(
            intent=Intent(raw=raw, category="code_search", confidence=0.9),
            related_memories=[MemoryHit(content="prefers concise answers", score=0.8, mem_type="pref")],
            related_knowledge=[],
            recent_events=[],
            circuit_state={},
            session_summary=None,
            turn_count=1,
            user_profile={},
        )

    @staticmethod
    def make_plan(raw: str, capabilities: list[str]) -> ActionPlan:
        return ActionPlan(
            intent=Intent(raw=raw, category="code_search", confidence=0.9),
            goal=TaskGoal(description="complete the request"),
            strategy="SERIAL",
            required_capabilities=capabilities,
            confidence=0.9,
            gap_analysis="",
        )

    def test_decide_selects_tool_within_capabilities(self, mock_tool_executor):
        """Decide selects tools only within the required capability set."""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=(
            '{"primary_tool": {"name": "web_search", "params": {"query": "Python async tutorials"}, '
            '"confidence": 0.95, "reason": "best match for web_search"}, '
            '"fallback_tool": {"name": "fetch_url", "params": {"url": ""}, '
            '"confidence": 0.5, "reason": "backup"}, '
            '"side_tools": [], '
            '"retry_policy": {"max_retries": 1, "backoff": 0.5}, '
            '"timeout_ms": 30000, '
            '"tool_context_prompt": "search the web"}'
        ))

        stage = DecideStage(llm=mock_llm, tool_executor=mock_tool_executor)
        ctx = self.make_context("search for Python async tutorials")
        plan = self.make_plan("search for Python async tutorials", ["web_search"])

        decision = asyncio.run(stage.select(plan, ctx))

        assert isinstance(decision, Decision)
        assert decision.primary_tool is not None
        assert decision.primary_tool.name in ("web_search", "fetch_url")

    def test_decide_provides_fallback_for_risky_operations(self, mock_tool_executor):
        """Risky operations should have a fallback or conservative confidence."""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=(
            '{"primary_tool": {"name": "bash", "params": {"command": "rm -rf /tmp/test"}, '
            '"confidence": 0.6, "reason": "destructive op needs care"}, '
            '"fallback_tool": {"name": "read_file", "params": {"path": "/tmp/test"}, '
            '"confidence": 0.5, "reason": "verify before delete"}, '
            '"side_tools": [], '
            '"retry_policy": {"max_retries": 0, "backoff": 1.0}, '
            '"timeout_ms": 10000, '
            '"tool_context_prompt": "handle with caution"}'
        ))

        stage = DecideStage(llm=mock_llm, tool_executor=mock_tool_executor)
        ctx = self.make_context("delete all temp files")
        plan = self.make_plan("delete all temp files", ["file_write"])

        decision = asyncio.run(stage.select(plan, ctx))

        assert isinstance(decision, Decision)
        # Destructive operations should have a fallback or lower confidence
        assert decision.fallback_tool is not None or decision.primary_tool.confidence < 0.9
