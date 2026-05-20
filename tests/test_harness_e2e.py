"""
SEAI Harness 工程单元测试
覆盖：约束引擎、反馈循环、端到端集成
"""
import asyncio
import json
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

from seai.core.constraint_engine import (
    ConstraintEngine, BoundaryType, BoundaryRule, ConstraintCheck
)
from seai.core.feedback_loop import (
    FeedbackLoop, FeedbackSource, FeedbackSeverity,
    FeedbackSignal, FeedbackRule, FeedbackAction,
)


class TestConstraintEngine:

    def test_initialization(self):
        engine = ConstraintEngine()
        assert len(engine._rules) > 0
        assert BoundaryType.FILE_READ in engine._rules

    def test_file_read_allowed(self):
        engine = ConstraintEngine()
        result = engine.check_file_access("src/main.py", "read")
        assert result.passed is True

    def test_file_read_blocked_sensitive(self):
        engine = ConstraintEngine()
        result = engine.check_file_access(".env", "read")
        assert result.passed is False

    def test_file_write_allowed(self):
        engine = ConstraintEngine()
        result = engine.check_file_access("src/new_file.py", "write")
        assert result.passed is True

    def test_file_write_blocked_key(self):
        engine = ConstraintEngine()
        result = engine.check_file_access("secrets.key", "write")
        assert result.passed is False

    def test_file_delete_blocked(self):
        engine = ConstraintEngine()
        result = engine.check_file_access("src/main.py", "delete")
        assert result.passed is False

    def test_file_delete_allowed_in_output(self):
        engine = ConstraintEngine()
        result = engine.check_file_access("output/temp.txt", "delete")
        assert result.passed is True

    def test_path_depth_limit(self):
        engine = ConstraintEngine()
        deep_path = "/".join(["src"] + ["sub"] * 20 + ["file.py"])
        result = engine.check_file_access(deep_path, "read")
        assert result.passed is False
        assert "深度" in result.message

    def test_network_domain_allowed(self):
        engine = ConstraintEngine()
        result = engine.check_network_access("api.github.com", 443)
        assert result.passed is True

    def test_network_domain_blocked(self):
        engine = ConstraintEngine()
        result = engine.check_network_access("localhost", 8080)
        assert result.passed is False

    def test_network_port_blocked(self):
        engine = ConstraintEngine()
        result = engine.check_network_access("example.com", 3306)
        assert result.passed is False

    def test_resource_limit_exceeded(self):
        engine = ConstraintEngine()
        result = engine.check_resource(BoundaryType.COMPUTE_TIME, 500.0)
        assert result.passed is False

    def test_resource_limit_ok(self):
        engine = ConstraintEngine()
        result = engine.check_resource(BoundaryType.COMPUTE_TIME, 100.0)
        assert result.passed is True

    def test_violation_tracking(self):
        engine = ConstraintEngine()
        engine.check_file_access(".env", "read")
        violations = engine.get_violations()
        assert len(violations) >= 1

    def test_violation_clear(self):
        engine = ConstraintEngine()
        engine.check_file_access(".env", "read")
        violations = engine.get_violations(clear=True)
        assert len(violations) >= 1
        assert len(engine.get_violations()) == 0

    def test_update_rule(self):
        engine = ConstraintEngine()
        engine.update_rule(BoundaryType.COMPUTE_TIME, {"max_value": 600.0})
        rule = engine.get_rule(BoundaryType.COMPUTE_TIME)
        assert rule.max_value == 600.0

    def test_disable_rule(self):
        engine = ConstraintEngine()
        engine.update_rule(BoundaryType.FILE_READ, {"enabled": False})
        result = engine.check_file_access(".env", "read")
        assert result.passed is True

    def test_stats(self):
        engine = ConstraintEngine()
        stats = engine.get_stats()
        assert stats["total_rules"] > 0
        assert "enabled_rules" in stats

    def test_pattern_matching_wildcard(self):
        engine = ConstraintEngine()
        assert engine._match_pattern("file.key", "*.key")
        assert engine._match_pattern("file.pem", "*.pem")
        assert not engine._match_pattern("file.txt", "*.key")

    def test_load_custom_rules(self, tmp_path):
        config_path = tmp_path / "rules.json"
        config_path.write_text(json.dumps({
            "file_read": {
                "allowed": ["/custom/"],
                "blocked": [],
                "max_value": None,
                "enabled": True,
            }
        }))
        engine = ConstraintEngine(config_path=config_path)
        rule = engine.get_rule(BoundaryType.FILE_READ)
        assert "/custom/" in rule.allowed


class TestFeedbackLoop:

    def test_initialization(self):
        loop = FeedbackLoop()
        assert len(loop._rules) > 0

    def test_emit_signal(self):
        loop = FeedbackLoop()
        loop.emit(
            source=FeedbackSource.TOOL_FAILURE,
            title="工具执行失败",
            detail="read_file 超时",
            metadata={"tool_name": "read_file"},
            severity=FeedbackSeverity.CRITICAL,
        )
        signals = loop._signals.get("tool_failure", [])
        assert len(signals) == 1
        assert signals[0].title == "工具执行失败"
        assert signals[0].severity == FeedbackSeverity.CRITICAL

    @pytest.mark.asyncio
    async def test_emit_multiple_signals(self):
        loop = FeedbackLoop()
        for i in range(10):
            loop.emit(
                source=FeedbackSource.TOOL_FAILURE,
                title=f"错误 {i}",
                metadata={"tool_name": "read_file"},
                severity=FeedbackSeverity.HIGH,
            )
        signals = loop._signals.get("tool_failure", [])
        assert len(signals) == 10

    def test_signal_threshold_not_triggered(self):
        loop = FeedbackLoop()
        handler_called = []

        async def handler(source, signals, rule):
            handler_called.append(True)
            return {"status": "ok"}

        loop.register_handler("auto_fix_tool", handler)

        loop.emit(
            source=FeedbackSource.TOOL_FAILURE,
            title="错误",
            metadata={"tool_name": "read_file"},
            severity=FeedbackSeverity.HIGH,
        )

        assert len(handler_called) == 0

    def test_register_handler(self):
        loop = FeedbackLoop()
        loop.register_handler("test_action", lambda s, sig, r: {"ok": True})
        assert "test_action" in loop._handlers

    def test_get_stats(self):
        loop = FeedbackLoop()
        loop.emit(source=FeedbackSource.TOOL_FAILURE, title="错误")
        stats = loop.get_stats()
        assert stats["total_signals"] == 1
        assert stats["recent_signals_1h"] == 1

    def test_get_unprocessed_signals(self):
        loop = FeedbackLoop()
        loop.emit(source=FeedbackSource.TOOL_FAILURE, title="错误1")
        loop.emit(source=FeedbackSource.TOOL_FAILURE, title="错误2")
        unprocessed = loop.get_unprocessed_signals(FeedbackSource.TOOL_FAILURE)
        assert len(unprocessed) == 2

    def test_mark_processed(self):
        loop = FeedbackLoop()
        loop.emit(source=FeedbackSource.TOOL_FAILURE, title="错误")
        loop.mark_processed(FeedbackSource.TOOL_FAILURE)
        unprocessed = loop.get_unprocessed_signals(FeedbackSource.TOOL_FAILURE)
        assert len(unprocessed) == 0

    def test_update_rule(self):
        loop = FeedbackLoop()
        loop.update_rule(FeedbackSource.TOOL_FAILURE, {"threshold": 10, "cooldown_seconds": 600.0})
        rule = loop._rules[FeedbackSource.TOOL_FAILURE]
        assert rule.threshold == 10
        assert rule.cooldown_seconds == 600.0

    def test_get_recent_actions_empty(self):
        loop = FeedbackLoop()
        actions = loop.get_recent_actions()
        assert actions == []

    @pytest.mark.asyncio
    async def test_max_signals_limit(self):
        loop = FeedbackLoop()
        loop._max_signals = 20
        for i in range(30):
            loop.emit(source=FeedbackSource.TOOL_FAILURE, title=f"错误 {i}")
        total = sum(len(v) for v in loop._signals.values())
        assert total <= loop._max_signals

    def test_multiple_sources(self):
        loop = FeedbackLoop()
        loop.emit(source=FeedbackSource.TOOL_FAILURE, title="工具错误")
        loop.emit(source=FeedbackSource.MICRO_REFLECT, title="反思警告")
        loop.emit(source=FeedbackSource.CIRCUIT_BREAKER, title="熔断触发")
        stats = loop.get_stats()
        assert len(stats["signals_by_source"]) >= 3


class TestHarnessIntegration:
    """端到端集成测试"""

    @pytest.mark.asyncio
    async def test_constraint_engine_in_agent(self):
        from seai.core.constraint_engine import ConstraintEngine
        engine = ConstraintEngine()
        engine.update_rule(BoundaryType.FILE_READ, {"enabled": True})
        result1 = engine.check_file_access("src/agent.py", "read")
        assert result1.passed
        result2 = engine.check_file_access(".env", "read")
        assert not result2.passed

    @pytest.mark.asyncio
    async def test_feedback_loop_in_agent(self):
        from seai.core.feedback_loop import FeedbackLoop, FeedbackSource, FeedbackSeverity

        loop = FeedbackLoop()
        action_results = []

        async def test_handler(source, signals, rule):
            action_results.append({"source": source, "count": len(signals)})
            return {"status": "ok"}

        loop.register_handler("test_handler", test_handler)

        loop.emit(
            source=FeedbackSource.TOOL_FAILURE,
            title="测试信号",
            severity=FeedbackSeverity.HIGH,
        )

        assert len(action_results) == 0

    @pytest.mark.asyncio
    async def test_feedback_signal_format(self):
        signal = FeedbackSignal(
            source=FeedbackSource.TOOL_FAILURE,
            severity=FeedbackSeverity.CRITICAL,
            title="关键错误",
            detail="详细描述",
            metadata={"key": "value"},
        )
        assert signal.source == FeedbackSource.TOOL_FAILURE
        assert signal.severity == FeedbackSeverity.CRITICAL
        assert signal.processed is False
        assert isinstance(signal.timestamp, float)

    @pytest.mark.asyncio
    async def test_boundary_rule_creation(self):
        rule = BoundaryRule(
            boundary_type=BoundaryType.FILE_READ,
            allowed=["src/"],
            blocked=[".env"],
            max_value=10.0,
        )
        assert rule.boundary_type == BoundaryType.FILE_READ
        assert rule.enabled is True
        assert "src/" in rule.allowed

    @pytest.mark.asyncio
    async def test_feedback_rule_cooldown(self):
        rule = FeedbackRule(
            source=FeedbackSource.TOOL_FAILURE,
            severity=FeedbackSeverity.HIGH,
            threshold=5,
            cooldown_seconds=300.0,
        )
        assert rule.threshold == 5
        assert rule.cooldown_seconds == 300.0