"""Orient stage — analyzes SituationContext and produces ActionPlan with strategy."""
import asyncio
import json
import time
from loguru import logger

from .types import (
    SituationContext,
    ActionPlan,
    TaskGoal,
    SubTask,
    ExecutionStrategy,
)
from .providers import KGProvider
from ..interfaces.llm_provider import LLMProvider
from .prompts import ORIENT_PROMPT, ORIENT_PROMPT_SIMPLE

class OrientStage:
    """Analyzes SituationContext and determines strategy + required capabilities."""

    def __init__(self, llm: LLMProvider, kg: KGProvider, timeout_ms: int = 30_000,
                 cache_ttl_s: float = 60.0):
        self._llm = llm
        self._timeout_ms = timeout_ms
        self._cache_ttl_s = cache_ttl_s
        self._cache: dict[str, tuple[float, ActionPlan]] = {}

    async def analyze(self, situation: SituationContext) -> ActionPlan:
        # Check cache for identical intent
        cache_key = f"{situation.intent.raw}|{situation.intent.category}"
        if cache_key in self._cache:
            cached_at, cached_plan = self._cache[cache_key]
            if time.time() - cached_at < self._cache_ttl_s:
                return cached_plan

        # Select prompt template by complexity
        is_simple = (
            situation.intent.confidence > 0.8
            and situation.turn_count <= 2
            and not situation.related_memories
        )
        template = ORIENT_PROMPT_SIMPLE if is_simple else ORIENT_PROMPT

        last_tool_results = json.dumps(
            {k: str(v)[:200] for k, v in situation.last_tool_results.items()}
        ) if situation.last_tool_results else "none"

        prompt = template.format(
            intent_raw=situation.intent.raw,
            intent_category=situation.intent.category,
            intent_confidence=situation.intent.confidence,
            turn_count=situation.turn_count,
            memory_summary=self._summarize_memories(situation),
            user_profile=json.dumps(situation.user_profile, ensure_ascii=False),
            last_tool_results=last_tool_results,
            context_usage_ratio=situation.context_usage_ratio,
        )

        messages = [{"role": "user", "content": prompt}]
        try:
            response = await asyncio.wait_for(
                self._llm.chat(messages),
                timeout=self._timeout_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Orient LLM timed out after {self._timeout_ms}ms, using defaults")
            return self._parse_response("", situation)

        parsed = self._parse_response(response, situation)

        # Retry once if JSON parsing failed
        if parsed.confidence == 0.5 and not parsed.required_capabilities:
            logger.info("Orient JSON parse failed, retrying LLM call once")
            try:
                retry_response = await asyncio.wait_for(
                    self._llm.chat([
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": response},
                        {"role": "user", "content": "Invalid JSON. Return ONLY the JSON object as specified."},
                    ]),
                    timeout=self._timeout_ms / 1000.0,
                )
                parsed = self._parse_response(retry_response, situation)
            except (asyncio.TimeoutError, Exception):
                pass

        self._cache[cache_key] = (time.time(), parsed)
        return parsed

    def _summarize_memories(self, situation: SituationContext) -> str:
        if not situation.related_memories:
            return "none"
        return "; ".join(
            m.content if hasattr(m, 'content') and isinstance(m.content, str) else str(m)
            for m in situation.related_memories[:5]
        )

    def _parse_response(self, raw: str, situation: SituationContext) -> ActionPlan:
        try:
            json_str = raw.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            data = json.loads(json_str)
        except json.JSONDecodeError:
            logger.warning(f"Orient LLM produced invalid JSON, using defaults. Raw: {raw[:200]}")
            data = {}

        strategy = data.get("strategy", "SERIAL")
        if strategy not in ("SERIAL", "PARALLEL", "BID", "FALLBACK"):
            strategy = "SERIAL"

        sub_tasks = None
        if data.get("sub_tasks"):
            sub_tasks = [
                SubTask(description=st["description"], capability=st["capability"])
                for st in data["sub_tasks"]
            ]

        fallback_strategy = data.get("fallback_strategy")
        if fallback_strategy not in ("SERIAL", "PARALLEL", "BID", "FALLBACK", None):
            fallback_strategy = None

        return ActionPlan(
            intent=situation.intent,
            goal=TaskGoal(description=data.get("goal_description", situation.intent.raw)),
            gap_analysis=data.get("gap_analysis", ""),
            strategy=strategy,  # type: ignore[arg-type]
            required_capabilities=data.get("required_capabilities", []),
            confidence=float(data.get("confidence", 0.5)),
            sub_tasks=sub_tasks,
            estimated_tool_calls=int(data.get("estimated_tool_calls", 1)),
            fallback_conditions=data.get("fallback_conditions", []),
            fallback_strategy=fallback_strategy,  # type: ignore[arg-type]
        )
