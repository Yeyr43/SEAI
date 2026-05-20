"""Act stage — tool execution with retry, fallback, and evolution signals."""
import asyncio
import time
from loguru import logger

from .types import (
    SituationContext, Decision, ToolBinding, RetryPolicy,
    ActionResult, EvolutionSignal,
)


class ActStage:
    """Executes tool decisions with retry, fallback, and side-tool parallelism."""

    def __init__(self, tool_executor, memory, kg, event_bus):
        self._tool_executor = tool_executor
        self._event_bus = event_bus

    async def execute(self, decision: Decision, situation: SituationContext) -> ActionResult:
        t0 = time.perf_counter()
        evolution_signals: list[EvolutionSignal] = []
        strategy = decision.strategy

        primary_tool = decision.primary_tool
        primary_tool_name = primary_tool.name if primary_tool else None

        # Check circuit breaker before executing
        circuit_blocked = False
        if primary_tool_name:
            status = self._event_bus.circuit_status(primary_tool_name)
            if status == "open":
                circuit_blocked = True
                primary_error = "Circuit breaker open — tool blocked"
                sig = EvolutionSignal(
                    type="circuit_open",
                    tool=primary_tool_name,
                    reason=primary_error,
                    severity=0.9,
                )
                evolution_signals.append(sig)
                await self._publish_signal(sig)

        primary_result = None
        primary_error = primary_error if circuit_blocked else None
        fallback_used = False
        fallback_tool_name = None
        fallback_result = None
        side_results: dict[str, str] = {}

        # ── Strategy: BID — execute primary + fallback concurrently ──
        if strategy == "BID" and not circuit_blocked:
            primary_task = self._execute_with_retry(
                primary_tool, decision.retry_policy, decision.timeout_ms)
            fallback_task = None
            if decision.fallback_tool:
                fallback_task = asyncio.create_task(
                    self._tool_executor.execute(
                        decision.fallback_tool.name, decision.fallback_tool.params))

            try:
                primary_result = await primary_task
                if primary_tool_name:
                    self._event_bus.circuit_on_success(primary_tool_name)
                if fallback_task and not fallback_task.done():
                    fallback_task.cancel()
            except Exception as exc:
                primary_error = str(exc)
                if primary_tool_name:
                    self._event_bus.circuit_on_failure(primary_tool_name)
                if fallback_task:
                    try:
                        fallback_result = await fallback_task
                        fallback_used = True
                        fallback_tool_name = decision.fallback_tool.name
                        self._event_bus.circuit_on_success(decision.fallback_tool.name)
                    except Exception as fe:
                        self._event_bus.circuit_on_failure(decision.fallback_tool.name)
                        sig = EvolutionSignal(
                            type="tool_failure", tool=primary_tool_name or "unknown",
                            reason=primary_error, severity=1.0)
                        evolution_signals.append(sig)
                        await self._publish_signal(sig)

        # ── Strategy: PARALLEL — primary + side tools concurrently ──
        elif strategy == "PARALLEL" and not circuit_blocked:
            tasks = {
                "primary": self._execute_with_retry(
                    primary_tool, decision.retry_policy, decision.timeout_ms),
            }
            for st in decision.side_tools:
                tasks[f"side:{st.name}"] = self._tool_executor.execute(st.name, st.params)

            gathered = dict(zip(
                tasks.keys(),
                await asyncio.gather(*tasks.values(), return_exceptions=True)))

            primary_outcome = gathered.pop("primary")
            if isinstance(primary_outcome, Exception):
                primary_error = str(primary_outcome)
                if primary_tool_name:
                    self._event_bus.circuit_on_failure(primary_tool_name)
            else:
                primary_result = primary_outcome
                if primary_tool_name:
                    self._event_bus.circuit_on_success(primary_tool_name)

            for key, val in gathered.items():
                st_name = key.removeprefix("side:")
                side_results[st_name] = f"error: {val}" if isinstance(val, Exception) else val

            # Fallback on parallel primary failure
            if primary_error and decision.fallback_tool:
                try:
                    fallback_result = await self._tool_executor.execute(
                        decision.fallback_tool.name, decision.fallback_tool.params)
                    fallback_used = True
                    fallback_tool_name = decision.fallback_tool.name
                    self._event_bus.circuit_on_success(decision.fallback_tool.name)
                except Exception as fe:
                    self._event_bus.circuit_on_failure(decision.fallback_tool.name)
                    sig = EvolutionSignal(
                        type="tool_failure", tool=primary_tool_name or "unknown",
                        reason=primary_error, severity=1.0)
                    evolution_signals.append(sig)
                    await self._publish_signal(sig)
            elif primary_error:
                sig = EvolutionSignal(
                    type="tool_failure", tool=primary_tool_name or "unknown",
                    reason=primary_error, severity=0.8)
                evolution_signals.append(sig)
                await self._publish_signal(sig)

        # ── Strategy: SERIAL / FALLBACK / default ──
        else:
            if not circuit_blocked:
                try:
                    primary_result = await self._execute_with_retry(
                        primary_tool, decision.retry_policy, decision.timeout_ms)
                    if primary_tool_name:
                        self._event_bus.circuit_on_success(primary_tool_name)
                except Exception as exc:
                    primary_error = str(exc)
                    if primary_tool_name:
                        self._event_bus.circuit_on_failure(primary_tool_name)

            if primary_error is not None:
                if decision.fallback_tool:
                    try:
                        fallback_result = await self._tool_executor.execute(
                            decision.fallback_tool.name, decision.fallback_tool.params)
                        fallback_used = True
                        fallback_tool_name = decision.fallback_tool.name
                        self._event_bus.circuit_on_success(decision.fallback_tool.name)
                    except Exception as fe:
                        logger.warning(f"Fallback tool also failed: {fe}")
                        self._event_bus.circuit_on_failure(decision.fallback_tool.name)
                        sig = EvolutionSignal(
                            type="tool_failure", tool=primary_tool_name or "unknown",
                            reason=primary_error, severity=1.0)
                        evolution_signals.append(sig)
                        await self._publish_signal(sig)
                elif not circuit_blocked:
                    sig = EvolutionSignal(
                        type="tool_failure", tool=primary_tool_name or "unknown",
                        reason=primary_error, severity=0.8)
                    evolution_signals.append(sig)
                    await self._publish_signal(sig)

            # Execute side tools sequentially after primary
            for st in decision.side_tools:
                try:
                    side_results[st.name] = await self._tool_executor.execute(st.name, st.params)
                except Exception as e:
                    side_results[st.name] = f"error: {e}"

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        success = primary_error is None or fallback_used

        return ActionResult(
            success=success,
            primary_tool=primary_tool_name or "",
            primary_result=primary_result,
            primary_error=primary_error,
            fallback_used=fallback_used,
            fallback_tool=fallback_tool_name,
            fallback_result=fallback_result,
            side_results=side_results,
            elapsed_ms=elapsed_ms,
            evolution_signals=evolution_signals,
        )

    async def _execute_with_retry(self, tool: ToolBinding | None, policy: RetryPolicy,
                                   timeout_ms: int = 30_000):
        if tool is None:
            raise RuntimeError("No primary tool specified")
        last_exc = None
        timeout_s = timeout_ms / 1000.0
        for attempt in range(policy.max_retries + 1):
            try:
                return await asyncio.wait_for(
                    self._tool_executor.execute(tool.name, tool.params),
                    timeout=timeout_s,
                )
            except asyncio.TimeoutError:
                last_exc = RuntimeError(f"Tool {tool.name} timed out after {timeout_ms}ms")
                if attempt < policy.max_retries:
                    await asyncio.sleep(policy.backoff)
            except Exception as e:
                last_exc = e
                if attempt < policy.max_retries:
                    await asyncio.sleep(policy.backoff)
        raise last_exc  # type: ignore[misc]

    async def _publish_signal(self, signal: EvolutionSignal) -> None:
        try:
            await self._event_bus.publish_evolution_signal({
                "type": signal.type,
                "tool": signal.tool,
                "reason": signal.reason,
                "severity": signal.severity,
            })
        except Exception:
            pass
