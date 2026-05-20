"""EvolutionBridge — OODA EvolutionSignal → EvolutionService + FeedbackLoop.

Accumulates per-tool failure counts with time-window decay. Triggers auto_fix
when a tool crosses the failure threshold (moderate severity), and deep_evolve
on high-severity signals with debounce protection.
"""
import asyncio
import time

from .types import EvolutionSignal


class EvolutionBridge:
    """Bridges OODA EvolutionSignals to EvolutionService and FeedbackLoop."""

    def __init__(self, event_bus=None, evolution_service=None, feedback_loop=None,
                 failure_threshold=2, deep_evolve_threshold=3,
                 window_s: float = 300.0, deep_evolve_cooldown_s: float = 60.0):
        self._event_bus = event_bus
        self._evolution_service = evolution_service
        self._feedback_loop = feedback_loop
        self._failure_threshold = failure_threshold
        self._deep_evolve_threshold = deep_evolve_threshold
        self._window_s = window_s
        self._deep_evolve_cooldown_s = deep_evolve_cooldown_s
        self._failures: dict[str, list[float]] = {}
        self._last_deep_evolve: float = 0.0
        self._pending_tasks: set = set()

        if event_bus:
            event_bus.subscribe_evolution(self._on_evolution_signal)

    @property
    def total_failures(self) -> int:
        self._expire()
        return sum(len(ts) for ts in self._failures.values())

    def failure_count(self, tool_name: str) -> int:
        self._expire()
        return len(self._failures.get(tool_name, []))

    def _expire(self) -> None:
        """Remove failures older than the time window."""
        cutoff = time.time() - self._window_s
        for tool in list(self._failures):
            self._failures[tool] = [ts for ts in self._failures[tool] if ts > cutoff]
            if not self._failures[tool]:
                del self._failures[tool]

    async def process_signals(self, signals: list) -> None:
        self._expire()
        for signal in signals:
            if isinstance(signal, dict):
                signal = EvolutionSignal(**signal)

            if signal.type != "tool_failure":
                continue

            self._failures.setdefault(signal.tool, []).append(time.time())

            severity = signal.severity

            # Auto-fix at threshold (moderate+ severity)
            if severity >= 0.5 and len(self._failures[signal.tool]) >= self._failure_threshold:
                await self._evolution_service.auto_fix_tool(
                    signal.tool, signal.reason, {})
                self._failures[signal.tool] = []

            # Deep evolve on high severity or total failure threshold (debounced)
            total = sum(len(ts) for ts in self._failures.values())
            should_deep = (
                severity >= 0.9 or
                total >= self._deep_evolve_threshold
            )
            if should_deep:
                now = time.time()
                if now - self._last_deep_evolve >= self._deep_evolve_cooldown_s:
                    self._last_deep_evolve = now
                    await self._evolution_service.deep_evolve()

            self._feedback_loop.add_signal(signal)

    def _on_evolution_signal(self, signal_dict: dict) -> None:
        task = asyncio.create_task(self.process_signals([signal_dict]))
        self._pending_tasks.add(task)
        task.add_done_callback(self._pending_tasks.discard)
