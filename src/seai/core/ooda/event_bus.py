"""OODAEventBus — async event bus with circuit breaker, implements EventBusProvider.

Wraps the existing AsyncEventBus and CircuitBreaker into the OODA Protocol
so the Observe stage can snapshot tool events + circuit states in one call.
"""
import asyncio
import time
from collections import deque
from typing import Any, Callable
from loguru import logger

from .types import BusEvent, CircuitStatus, CircuitConfig
from .providers import EventBusProvider


class OODAEventBus(EventBusProvider):
    """Async event bus for OODA — tool events, circuit breaker, evolution signals."""

    def __init__(self, max_history: int = 500,
                 default_circuit_config: CircuitConfig | None = None,
                 tool_circuit_configs: dict[str, CircuitConfig] | None = None):
        self._events: deque[BusEvent] = deque(maxlen=max_history)
        self._max_history = max_history
        self._circuits: dict[str, _Circuit] = {}
        self._evolution_subscribers: list[Callable] = []
        self._lock = asyncio.Lock()
        self._default_circuit_config = default_circuit_config or CircuitConfig()
        self._tool_circuit_configs = tool_circuit_configs or {}

    def _circuit_config_for(self, name: str) -> CircuitConfig:
        return self._tool_circuit_configs.get(name, self._default_circuit_config)

    # ── EventBusProvider ──

    def snapshot(self) -> tuple[list[BusEvent], dict[str, CircuitStatus]]:
        circuits = {
            name: CircuitStatus(state=c.state, failures=c.failures)
            for name, c in self._circuits.items()
        }
        return list(self._events), circuits

    # ── Tool events ──

    async def publish_tool_started(self, tool_name: str, params: dict) -> None:
        await self._add_event("tool.started", {
            "tool": tool_name,
            "params": params,
        })

    async def publish_tool_completed(self, tool_name: str, result: Any,
                                      elapsed_ms: int = 0) -> None:
        await self._add_event("tool.completed", {
            "tool": tool_name,
            "result": str(result)[:500],
            "elapsed_ms": elapsed_ms,
        })

    async def publish_tool_failed(self, tool_name: str, error: str) -> None:
        await self._add_event("tool.failed", {
            "tool": tool_name,
            "error": error,
        })

    # ── Circuit breaker ──

    def circuit_on_success(self, name: str) -> None:
        c = self._get_or_create_circuit(name)
        cfg = self._circuit_config_for(name)
        if c.state == "closed":
            c.failures = max(0, c.failures - 1)
        elif c.state == "half_open":
            c.half_open_count += 1
            if c.half_open_count >= cfg.half_open_success_threshold:
                c.state = "closed"
                c.failures = 0
                c.half_open_count = 0
                self._on_circuit_state_change(name, "half_open", "closed")

    def circuit_on_failure(self, name: str) -> None:
        c = self._get_or_create_circuit(name)
        cfg = self._circuit_config_for(name)
        prev_state = c.state
        c.failures += 1
        c.last_failure = time.time()
        if c.failures >= cfg.failure_threshold and c.state != "open":
            c.state = "open"
            c.opened_at = time.time()
            self._on_circuit_state_change(name, prev_state, "open")

    def circuit_status(self, name: str) -> str:
        """Return circuit state: 'closed', 'open', or 'half_open'."""
        c = self._get_or_create_circuit(name)
        return c.state

    def _get_or_create_circuit(self, name: str) -> "_Circuit":
        if name not in self._circuits:
            self._circuits[name] = _Circuit()
        c = self._circuits[name]
        cfg = self._circuit_config_for(name)
        # Auto-transition open → half_open after cooldown
        if c.state == "open" and c.opened_at:
            if time.time() - c.opened_at >= cfg.cooldown_s:
                c.state = "half_open"
                c.half_open_count = 0
                self._on_circuit_state_change(name, "open", "half_open")
        return c

    def _on_circuit_state_change(self, name: str, old_state: str, new_state: str) -> None:
        """Log and publish notification on circuit state transitions."""
        logger.info(f"Circuit [{name}]: {old_state} → {new_state}")
        try:
            asyncio.create_task(
                self._add_event("circuit.state_change", {
                    "tool": name,
                    "old_state": old_state,
                    "new_state": new_state,
                })
            )
        except RuntimeError:
            # No running event loop (e.g., in tests) — event is dropped
            pass

    # ── Evolution signals ──

    def subscribe_evolution(self, handler: Callable) -> None:
        self._evolution_subscribers.append(handler)

    async def publish_evolution_signal(self, signal: dict) -> None:
        for handler in self._evolution_subscribers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(signal)
                else:
                    handler(signal)
            except Exception:
                pass

    # ── Lifecycle ──

    def clear(self) -> None:
        self._events.clear()
        self._circuits.clear()

    # ── Internal ──

    async def _add_event(self, topic: str, data: dict) -> None:
        async with self._lock:
            self._events.append(BusEvent(
                topic=topic,
                data=data,
                ts=time.time(),
            ))


class _Circuit:
    def __init__(self):
        self.state = "closed"
        self.failures = 0
        self.last_failure = 0.0
        self.opened_at: float | None = None
        self.half_open_count = 0
