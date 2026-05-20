"""
SEAI Harness 工程 - 闭环反馈驱动引擎
收集反馈信号 → 自动触发进化 → 验证改进效果
集成 EventBus 实现模块间解耦通信
"""
import asyncio
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger


class FeedbackSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class FeedbackSource(str, Enum):
    TOOL_FAILURE = "tool_failure"
    MICRO_REFLECT = "micro_reflect"
    USER_NEGATIVE = "user_negative"
    SKILL_LOW_SCORE = "skill_low_score"
    CIRCUIT_BREAKER = "circuit_breaker"
    CONSTRAINT_VIOLATION = "constraint_violation"
    REVIEWER_REJECTION = "reviewer_rejection"
    EVOLUTION_RESULT = "evolution_result"


@dataclass
class FeedbackSignal:
    source: FeedbackSource
    severity: FeedbackSeverity
    title: str
    detail: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    processed: bool = False


@dataclass
class FeedbackAction:
    name: str
    description: str = ""
    priority: int = 0


@dataclass
class FeedbackRule:
    source: FeedbackSource
    severity: FeedbackSeverity
    threshold: int = 3
    cooldown_seconds: float = 300.0
    action: FeedbackAction = field(default_factory=lambda: FeedbackAction(name="log"))


class FeedbackLoop:
    """闭环反馈驱动引擎 - 实施 Harness 工程中的反馈循环层
    集成 EventBus 实现模块间解耦通信"""

    DEFAULT_RULES = {
        FeedbackSource.TOOL_FAILURE: FeedbackRule(
            source=FeedbackSource.TOOL_FAILURE,
            severity=FeedbackSeverity.CRITICAL,
            threshold=5,
            cooldown_seconds=120.0,
            action=FeedbackAction(name="auto_fix_tool", description="自动修复工具", priority=10),
        ),
        FeedbackSource.MICRO_REFLECT: FeedbackRule(
            source=FeedbackSource.MICRO_REFLECT,
            severity=FeedbackSeverity.MEDIUM,
            threshold=3,
            cooldown_seconds=600.0,
            action=FeedbackAction(name="light_check", description="轻量进化检查", priority=5),
        ),
        FeedbackSource.SKILL_LOW_SCORE: FeedbackRule(
            source=FeedbackSource.SKILL_LOW_SCORE,
            severity=FeedbackSeverity.HIGH,
            threshold=2,
            cooldown_seconds=900.0,
            action=FeedbackAction(name="skill_curation", description="技能自动整理", priority=7),
        ),
        FeedbackSource.CIRCUIT_BREAKER: FeedbackRule(
            source=FeedbackSource.CIRCUIT_BREAKER,
            severity=FeedbackSeverity.CRITICAL,
            threshold=2,
            cooldown_seconds=120.0,
            action=FeedbackAction(name="circuit_reset", description="熔断重置检查", priority=10),
        ),
        FeedbackSource.CONSTRAINT_VIOLATION: FeedbackRule(
            source=FeedbackSource.CONSTRAINT_VIOLATION,
            severity=FeedbackSeverity.CRITICAL,
            threshold=1,
            cooldown_seconds=60.0,
            action=FeedbackAction(name="security_alert", description="安全告警", priority=10),
        ),
        FeedbackSource.REVIEWER_REJECTION: FeedbackRule(
            source=FeedbackSource.REVIEWER_REJECTION,
            severity=FeedbackSeverity.HIGH,
            threshold=2,
            cooldown_seconds=300.0,
            action=FeedbackAction(name="deep_evolve", description="深度进化", priority=8),
        ),
        FeedbackSource.EVOLUTION_RESULT: FeedbackRule(
            source=FeedbackSource.EVOLUTION_RESULT,
            severity=FeedbackSeverity.INFO,
            threshold=1,
            cooldown_seconds=3600.0,
            action=FeedbackAction(name="evolution_report", description="进化报告", priority=3),
        ),
    }

    def __init__(self, event_bus=None):
        self._signals: Dict[str, List[FeedbackSignal]] = {}
        self._rules: Dict[FeedbackSource, FeedbackRule] = {}
        self._rules.update(self.DEFAULT_RULES)
        self._action_history: List[dict] = []
        self._last_action_time: Dict[str, float] = {}
        self._handlers: Dict[str, Callable] = {}
        self._max_history = 200
        self._max_signals = 1000
        self._event_bus = event_bus
        self._custom_sources: Dict[str, FeedbackRule] = {}

    def register_handler(self, action_name: str, handler: Callable):
        self._handlers[action_name] = handler

    def register_source(self, source_name: str, rule: FeedbackRule):
        try:
            source = FeedbackSource(source_name)
        except ValueError:
            source = source_name
        self._rules[source] = rule
        self._custom_sources[source_name] = rule
        logger.info(f"注册自定义反馈源: {source_name}")

    def emit(
        self,
        source: FeedbackSource,
        title: str,
        detail: str = "",
        metadata: dict = None,
        severity: FeedbackSeverity = None,
    ) -> None:
        rule = self._rules.get(source)
        signal_severity = severity or (rule.severity if rule else FeedbackSeverity.MEDIUM)

        signal = FeedbackSignal(
            source=source,
            severity=signal_severity,
            title=title,
            detail=detail,
            metadata=metadata or {},
            timestamp=time.time(),
        )

        source_key = source.value if isinstance(source, FeedbackSource) else str(source)
        if source_key not in self._signals:
            self._signals[source_key] = []
        self._signals[source_key].append(signal)

        total = sum(len(v) for v in self._signals.values())
        if total > self._max_signals:
            oldest_key = min(self._signals.keys(),
                           key=lambda k: self._signals[k][0].timestamp if self._signals[k] else float("inf"))
            if self._signals[oldest_key]:
                self._signals[oldest_key].pop(0)

        if self._event_bus:
            try:
                from .event_bus import Event, EventPriority
                priority_map = {
                    FeedbackSeverity.CRITICAL: EventPriority.CRITICAL,
                    FeedbackSeverity.HIGH: EventPriority.HIGH,
                    FeedbackSeverity.MEDIUM: EventPriority.NORMAL,
                    FeedbackSeverity.LOW: EventPriority.LOW,
                    FeedbackSeverity.INFO: EventPriority.LOW,
                }
                event = Event(
                    event_type=f"feedback.{source_key}",
                    source="feedback_loop",
                    data={
                        "title": title,
                        "detail": detail,
                        "metadata": metadata or {},
                        "severity": signal_severity.value,
                    },
                    priority=priority_map.get(signal_severity, EventPriority.NORMAL),
                )
                asyncio.ensure_future(self._event_bus.publish(event))
            except Exception as e:
                logger.warning(f"事件总线发布失败: {e}")

        if rule:
            recent_count = sum(
                1 for s in self._signals.get(source_key, [])
                if s.timestamp > time.time() - 3600.0
            )
            if recent_count >= rule.threshold:
                try:
                    asyncio.create_task(self._maybe_trigger_action(source))
                except RuntimeError:
                    logger.debug("事件循环未运行，跳过反馈动作触发")

    async def _maybe_trigger_action(self, source: FeedbackSource):
        rule = self._rules.get(source)
        if not rule:
            return

        action_name = rule.action.name
        last_time = self._last_action_time.get(action_name, 0)
        if time.time() - last_time < rule.cooldown_seconds:
            return

        self._last_action_time[action_name] = time.time()

        handler = self._handlers.get(action_name)
        if handler:
            try:
                relevant_signals = [
                    s for s in self._signals.get(source.value, [])
                    if s.timestamp > time.time() - rule.cooldown_seconds * 2
                ]
                result = await handler(source, relevant_signals, rule)
                self._record_action(action_name, result)
                logger.info(f"反馈动作触发: {action_name} (source={source.value})")
            except Exception as e:
                logger.error(f"反馈动作执行失败 [{action_name}]: {e}")
                self._record_action(action_name, {"status": "error", "error": str(e)})

    def _record_action(self, action_name: str, result: Any):
        self._action_history.append({
            "action": action_name,
            "result": result,
            "timestamp": time.time(),
        })
        if len(self._action_history) > self._max_history:
            self._action_history = self._action_history[-self._max_history:]

    def get_stats(self) -> dict:
        total_signals = sum(len(v) for v in self._signals.values())
        recent_signals = sum(
            1 for signals in self._signals.values()
            for s in signals
            if s.timestamp > time.time() - 3600.0
        )
        recent_actions = sum(
            1 for a in self._action_history
            if a["timestamp"] > time.time() - 3600.0
        )

        return {
            "total_signals": total_signals,
            "recent_signals_1h": recent_signals,
            "total_actions": len(self._action_history),
            "recent_actions_1h": recent_actions,
            "signals_by_source": {
                source: len(signals)
                for source, signals in self._signals.items()
            },
            "rules_count": len(self._rules),
            "handlers_count": len(self._handlers),
        }

    def get_unprocessed_signals(self, source: FeedbackSource = None) -> List[FeedbackSignal]:
        if source:
            return [s for s in self._signals.get(source.value, []) if not s.processed]
        return [
            s for signals in self._signals.values()
            for s in signals if not s.processed
        ]

    def mark_processed(self, source: FeedbackSource, signal_count: int = None):
        signals = self._signals.get(source.value, [])
        count = signal_count or len(signals)
        for s in signals[:count]:
            s.processed = True

    def get_recent_actions(self, limit: int = 20) -> List[dict]:
        return self._action_history[-limit:]

    def update_rule(self, source: FeedbackSource, updates: dict):
        rule = self._rules.get(source)
        if rule:
            if "threshold" in updates:
                rule.threshold = updates["threshold"]
            if "cooldown_seconds" in updates:
                rule.cooldown_seconds = updates["cooldown_seconds"]
        else:
            self._rules[source] = FeedbackRule(
                source=source,
                severity=updates.get("severity", FeedbackSeverity.MEDIUM),
                threshold=updates.get("threshold", 3),
                cooldown_seconds=updates.get("cooldown_seconds", 300.0),
                action=FeedbackAction(name=updates.get("action", "log")),
            )