"""OODAContext — runtime session context wrapping the full OODA lifecycle.

Builds on top of types.py dataclasses. Manages:
- Initial SituationContext creation from raw input + providers
- Iteration history (plan → decision → result)
- Evolution signal accumulation
- Context exhaustion detection
- Loop summary generation
"""
from dataclasses import dataclass, field
import asyncio

from .types import (
    Intent, SituationContext, ActionPlan, Decision, ActionResult,
    EvolutionSignal, OODALoopConfig, build_action_summary,
)
from .providers import MemoryProvider, KGProvider, EventBusProvider
from .observe import ObserveStage


class OODAContext:
    """Runtime session state for a single OODA loop execution."""

    def __init__(self, intent: Intent | str, memory: MemoryProvider,
                 kg: KGProvider, event_bus: EventBusProvider,
                 config: OODALoopConfig | None = None):
        self._intent = self._normalize_intent(intent)
        self._memory = memory
        self._kg = kg
        self._event_bus = event_bus
        self.config = config or OODALoopConfig()

        self._observe = ObserveStage(
            memory=self._memory,
            kg=self._kg,
            event_bus=self._event_bus,
        )
        self._situation: SituationContext | None = None
        self._turn_count = 0
        self._history: list[dict] = []
        self._evolution_signals: list[EvolutionSignal] = []
        self._current_usage_ratio = 0.0
        self._last_result: ActionResult | None = None

    # ── Properties ──

    @property
    def intent(self) -> Intent:
        return self._intent

    @property
    def situation(self) -> SituationContext | None:
        return self._situation

    @property
    def iteration(self) -> int:
        return self._turn_count

    @property
    def history(self) -> list[dict]:
        return self._history

    @property
    def evolution_signals(self) -> list[EvolutionSignal]:
        return self._evolution_signals

    @property
    def last_result(self) -> ActionResult | None:
        return self._last_result

    # ── Gather (Observe) ──

    async def gather(self) -> SituationContext:
        """Run Observe stage to build/refresh SituationContext."""
        base = self._situation or SituationContext(intent=self._intent)
        self._situation = await self._observe.gather(base)
        self._turn_count += 1
        self._situation.turn_count = self._turn_count
        # Carry over context usage ratio
        self._situation.context_usage_ratio = self._current_usage_ratio
        return self._situation

    # ── Record ──

    def record_iteration(self, plan: ActionPlan | None, decision: Decision | None,
                         result: ActionResult) -> None:
        """Store one complete iteration in the history."""
        self._history.append({
            "plan": plan,
            "decision": decision,
            "result": result,
        })
        self._last_result = result
        self._evolution_signals.extend(result.evolution_signals)
        self._turn_count = len(self._history)

    # ── Context exhaustion ──

    def is_context_exhausted(self) -> bool:
        return self._current_usage_ratio > self.config.context_critical_ratio

    # ── Evolution ──

    def should_trigger_evolution(self) -> bool:
        if not self._evolution_signals:
            return False
        if self._turn_count < self.config.evolution_check_interval:
            return False
        failure_count = sum(1 for s in self._evolution_signals if s.type == "tool_failure")
        return failure_count >= self.config.evolution_check_interval

    # ── Summary ──

    def build_summary(self) -> str:
        return build_action_summary(
            [h["result"] for h in self._history],
            self._evolution_signals,
            intent_raw=self._intent.raw,
        )

    # ── Internal ──

    @staticmethod
    def _normalize_intent(raw: Intent | str) -> Intent:
        if isinstance(raw, Intent):
            return raw
        return Intent(raw=raw, category="general", confidence=0.5)
