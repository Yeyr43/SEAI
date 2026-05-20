"""OODA Loop coordinator — orchestrates Observe → Orient → Decide → Act."""
import asyncio
import time
from loguru import logger

from .types import (
    Intent, SituationContext, OODALoopConfig, OODAResult, EvolutionSignal,
    IterationTrace, build_action_summary, estimate_tokens,
)
from .observe import ObserveStage
from .orient import OrientStage
from .decide import DecideStage
from .act import ActStage


class OODALoop:
    """Orchestrates the full OODA loop for a single intent."""

    def __init__(self, observe: ObserveStage, orient: OrientStage,
                 decide: DecideStage, act: ActStage):
        self._observe = observe
        self._orient = orient
        self._decide = decide
        self._act = act

    async def run(self, intent: Intent, config: OODALoopConfig | None = None) -> OODAResult:
        config = config or OODALoopConfig()
        situation = SituationContext(intent=intent)
        actions = []
        all_evolution_signals: list[EvolutionSignal] = []
        traces: list[IterationTrace] = []
        loop_t0 = time.perf_counter()

        # Discover sub-tasks from initial Orient to drive iteration schedule
        sub_tasks: list = []
        plan = None
        total_tokens = 0

        for iteration in range(config.max_iterations):
            trace = IterationTrace(iteration=iteration + 1)

            # Observe (with per-iteration timeout safeguard)
            t0 = time.perf_counter()
            try:
                situation = await asyncio.wait_for(
                    self._observe.gather(situation),
                    timeout=config.default_timeout_ms / 1000.0,
                )
            except asyncio.TimeoutError:
                logger.warning(f"Observe timed out in iteration {iteration + 1}, reusing context")
            situation.turn_count = iteration + 1
            trace.observe_ms = int((time.perf_counter() - t0) * 1000)

            # Check context exhaustion
            if situation.context_usage_ratio > config.context_critical_ratio:
                logger.warning(
                    f"Context exhausted: {situation.context_usage_ratio:.2f} "
                    f"> {config.context_critical_ratio}"
                )
                return OODAResult(
                    status="context_exhausted",
                    summary=f"Stopped after {len(actions)} actions due to context exhaustion.",
                    situation=situation,
                    actions=actions,
                    evolution_triggered=len(all_evolution_signals) > 0,
                    trace=traces,
                    total_ms=int((time.perf_counter() - loop_t0) * 1000),
                    total_tokens=total_tokens,
                )

            # Set active sub-task if available
            if sub_tasks and iteration < len(sub_tasks):
                situation.active_subtask = sub_tasks[iteration].description
            else:
                situation.active_subtask = None

            # Orient (skip if sub-tasks already planned and we're mid-execution)
            t0 = time.perf_counter()
            if plan is not None and sub_tasks and iteration < len(sub_tasks):
                # Reuse plan, just advance the sub-task pointer
                pass
            else:
                try:
                    plan = await self._orient.analyze(situation)
                except Exception as e:
                    logger.warning(f"Orient failed: {e}, using fallback plan")
                    from .types import ActionPlan, TaskGoal
                    plan = ActionPlan(
                        intent=intent,
                        goal=TaskGoal(description=intent.raw),
                        strategy="SERIAL",
                        required_capabilities=["general"],
                        confidence=0.3,
                        gap_analysis=str(e),
                    )
                # Capture sub-tasks on first successful orient
                if not sub_tasks and plan.sub_tasks:
                    sub_tasks = list(plan.sub_tasks)
                    logger.info(f"Orient produced {len(sub_tasks)} sub-task(s), driving iteration schedule")
            trace.orient_ms = int((time.perf_counter() - t0) * 1000)
            trace.orient_strategy = plan.strategy
            trace.orient_capabilities = list(plan.required_capabilities)
            trace.orient_confidence = plan.confidence

            # Decide
            t0 = time.perf_counter()
            try:
                decision = await self._decide.select(plan, situation)
            except Exception as e:
                logger.warning(f"Decide failed: {e}, using minimal decision")
                from .types import Decision, ToolBinding, RetryPolicy
                decision = Decision(
                    primary_tool=ToolBinding(
                        name="web_search",
                        params={"query": intent.raw},
                        confidence=0.3,
                        reason="fallback",
                    ),
                    retry_policy=RetryPolicy(max_retries=0, backoff=1.0),
                )
            trace.decide_ms = int((time.perf_counter() - t0) * 1000)
            if decision.primary_tool:
                trace.decide_tool = decision.primary_tool.name
                trace.decide_confidence = decision.primary_tool.confidence

            # Act
            t0 = time.perf_counter()
            result = await self._act.execute(decision, situation)
            trace.act_ms = int((time.perf_counter() - t0) * 1000)
            trace.act_success = result.success
            trace.act_elapsed_ms = result.elapsed_ms
            trace.signals_count = len(result.evolution_signals)
            actions.append(result)
            traces.append(trace)

            # Collect evolution signals
            all_evolution_signals.extend(result.evolution_signals)

            # Feed tool results back into situation for next iteration
            if result.primary_result:
                situation.last_tool_results[result.primary_tool] = result.primary_result

            # Token estimation for this iteration (prompts + tool I/O)
            iter_tokens = (
                estimate_tokens(situation.intent.raw)
                + estimate_tokens(str(situation.last_tool_results))
                + 500  # prompt template overhead
            )
            result.tokens_used = iter_tokens
            total_tokens += iter_tokens

            # Structured per-iteration log
            logger.info(
                f"OODA iter {iteration + 1}/{config.max_iterations}: "
                f"observe={trace.observe_ms}ms orient={trace.orient_ms}ms "
                f"decide={trace.decide_ms}ms act={trace.act_ms}ms "
                f"strategy={trace.orient_strategy} tool={trace.decide_tool} "
                f"success={trace.act_success} tokens={iter_tokens}"
            )

            # Check evolution trigger
            if self._should_trigger_evolution(all_evolution_signals, config, iteration + 1):
                logger.info("Evolution triggered after repeated failures")
                return OODAResult(
                    status="completed",
                    summary=build_action_summary(actions, all_evolution_signals),
                    situation=situation,
                    actions=actions,
                    evolution_triggered=True,
                    trace=traces,
                    total_ms=int((time.perf_counter() - loop_t0) * 1000),
                    total_tokens=total_tokens,
                )

        total_ms = int((time.perf_counter() - loop_t0) * 1000)
        logger.info(
            f"OODA loop complete: {len(actions)} actions in {total_ms}ms, "
            f"tokens~{total_tokens} "
            f"{sum(1 for a in actions if a.success)}/{len(actions)} succeeded"
        )

        return OODAResult(
            status="completed",
            summary=build_action_summary(actions, all_evolution_signals),
            situation=situation,
            actions=actions,
            evolution_triggered=len(all_evolution_signals) > 0,
            trace=traces,
            total_ms=total_ms,
            total_tokens=total_tokens,
        )

    def _should_trigger_evolution(self, signals: list[EvolutionSignal],
                                   config: OODALoopConfig, iteration: int) -> bool:
        if not signals:
            return False
        if iteration < config.evolution_check_interval:
            return False
        # Trigger if failure count meets or exceeds the check interval
        failure_count = sum(1 for s in signals if s.type == "tool_failure")
        return failure_count >= config.evolution_check_interval

