"""Orient stage: unit tests for parsing + integration tests with real LLM."""
import asyncio
from unittest.mock import MagicMock, AsyncMock
import pytest

from seai.core.ooda.types import (
    SituationContext, Intent, ActionPlan, MemoryHit,
)
from seai.core.ooda.providers import KGProvider
from seai.core.ooda.orient import OrientStage, ORIENT_PROMPT
from seai.core.interfaces.llm_provider import LLMProvider


# ── Unit tests: response parsing (no LLM required) ──

class TestOrientParseResponse:
    """Tests for the _parse_response method."""

    @staticmethod
    def _make_context():
        intent = Intent(raw="test query", category="test", confidence=0.9)
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

    def test_parse_valid_json_response(self):
        stage = OrientStage(llm=MagicMock(), kg=MagicMock())
        ctx = self._make_context()
        response = (
            '{"strategy": "SERIAL", '
            '"required_capabilities": ["web_search"], '
            '"gap_analysis": "no issues found", '
            '"confidence": 0.95, '
            '"goal_description": "search the web for information", '
            '"sub_tasks": [{"description": "search web", "capability": "web_search"}], '
            '"estimated_tool_calls": 1, '
            '"fallback_strategy": null, '
            '"fallback_conditions": []}'
        )
        plan = stage._parse_response(response, ctx)
        assert plan.strategy == "SERIAL"
        assert plan.required_capabilities == ["web_search"]
        assert plan.gap_analysis == "no issues found"
        assert plan.confidence == 0.95
        assert plan.goal is not None
        assert len(plan.sub_tasks) == 1
        assert plan.fallback_strategy is None

    def test_parse_invalid_json_falls_back_to_defaults(self):
        stage = OrientStage(llm=MagicMock(), kg=MagicMock())
        ctx = self._make_context()
        plan = stage._parse_response("not valid json at all", ctx)
        assert plan.strategy == "SERIAL"
        assert plan.required_capabilities == []
        assert plan.confidence == 0.5

    def test_parse_code_fenced_json(self):
        stage = OrientStage(llm=MagicMock(), kg=MagicMock())
        ctx = self._make_context()
        response = (
            '```json\n'
            '{"strategy": "PARALLEL", '
            '"required_capabilities": ["read_file", "grep"], '
            '"gap_analysis": "need both tools", '
            '"confidence": 0.8, '
            '"goal_description": "find and read files in parallel", '
            '"sub_tasks": [], '
            '"estimated_tool_calls": 2, '
            '"fallback_strategy": null, '
            '"fallback_conditions": []}\n'
            '```'
        )
        plan = stage._parse_response(response, ctx)
        assert plan.strategy == "PARALLEL"
        assert len(plan.required_capabilities) == 2

    def test_prompt_includes_situation_context(self):
        prompt = ORIENT_PROMPT.format(
            intent_raw="find Rust code",
            intent_category="code_search",
            intent_confidence=0.95,
            turn_count=3,
            memory_summary="user prefers Rust",
            user_profile='{"name": "dev"}',
            last_tool_results="none",
            context_usage_ratio=0.2,
        )
        assert "find Rust code" in prompt
        assert "code_search" in prompt
        assert "0.95" in prompt
        assert "user prefers Rust" in prompt


# ── Integration tests (mock LLM, testing stage behavior end-to-end) ──


class TestOrientStageIntegration:
    """Orient stage integration tests with mock LLM responses."""

    @pytest.fixture
    def mock_kg(self):
        kg = MagicMock(spec=KGProvider)
        kg.query = AsyncMock(return_value=[])
        return kg

    @staticmethod
    def make_context(raw: str, category: str = "general") -> SituationContext:
        return SituationContext(
            intent=Intent(raw=raw, category=category, confidence=0.8),
            related_memories=[
                MemoryHit(content="user is a Python developer", score=0.9, mem_type="profile"),
            ],
            related_knowledge=[],
            recent_events=[],
            circuit_state={},
            session_summary=None,
            turn_count=2,
            user_profile={"name": "test-user"},
        )

    def test_orient_produces_action_plan_with_strategy(self, mock_kg):
        """Orient produces a valid ActionPlan with strategy selection."""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=(
            '{"strategy": "SERIAL", '
            '"required_capabilities": ["web_search", "read_file"], '
            '"gap_analysis": "need to search then read results", '
            '"confidence": 0.85, '
            '"goal_description": "find Python async best practices", '
            '"sub_tasks": [{"description": "search web", "capability": "web_search"}], '
            '"estimated_tool_calls": 2, '
            '"fallback_strategy": null, '
            '"fallback_conditions": []}'
        ))

        stage = OrientStage(llm=mock_llm, kg=mock_kg)
        context = self.make_context(
            raw="search for Python async best practices",
            category="code_search",
        )
        plan = asyncio.run(stage.analyze(context))

        assert isinstance(plan, ActionPlan)
        assert plan.strategy in ("SERIAL", "PARALLEL", "BID", "FALLBACK")
        assert len(plan.required_capabilities) > 0
        assert len(plan.gap_analysis) > 0
        assert 0.0 <= plan.confidence <= 1.0

    def test_orient_detects_missing_capabilities(self, mock_kg):
        """Orient identifies when capabilities are insufficient (low confidence)."""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=(
            '{"strategy": "FALLBACK", '
            '"required_capabilities": ["bash"], '
            '"gap_analysis": "infrastructure deployment requires k8s/aws tools - not available", '
            '"confidence": 0.3, '
            '"goal_description": "deploy k8s on AWS", '
            '"sub_tasks": [], '
            '"estimated_tool_calls": 0, '
            '"fallback_strategy": "SERIAL", '
            '"fallback_conditions": ["if web_search is available, search for workarounds"]}'
        ))

        stage = OrientStage(llm=mock_llm, kg=mock_kg)
        context = self.make_context(
            raw="deploy a Kubernetes cluster on AWS",
            category="infrastructure",
        )
        plan = asyncio.run(stage.analyze(context))

        assert len(plan.gap_analysis) > 0
        assert plan.confidence < 1.0
        assert plan.fallback_strategy is not None or plan.confidence < 0.8

    def test_orient_simple_query_serial_strategy(self, mock_kg):
        """Simple queries should get SERIAL strategy with high confidence."""
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=(
            '{"strategy": "SERIAL", '
            '"required_capabilities": ["web_search"], '
            '"gap_analysis": "trivial math question", '
            '"confidence": 0.99, '
            '"goal_description": "answer 2+2", '
            '"sub_tasks": [], '
            '"estimated_tool_calls": 1, '
            '"fallback_strategy": null, '
            '"fallback_conditions": []}'
        ))

        stage = OrientStage(llm=mock_llm, kg=mock_kg)
        context = self.make_context(raw="what is 2+2", category="math")
        plan = asyncio.run(stage.analyze(context))

        assert plan.strategy == "SERIAL"
        assert plan.confidence > 0.7
        assert len(plan.required_capabilities) <= 2
