"""Decide stage — constrained tool selection from ActionPlan capabilities."""
import asyncio
import json
from loguru import logger

from .types import (
    SituationContext,
    ActionPlan,
    Decision,
    ToolBinding,
    RetryPolicy,
    ToolStats,
)
from .prompts import DECIDE_PROMPT

# Capability → candidate tools (primary first, then fallbacks)
CAPABILITY_TOOL_MAP: dict[str, list[str]] = {
    "code_generation": ["bash", "execute_python", "write_file"],
    "web_search": ["web_search", "fetch_url"],
    "file_read": ["read_file", "grep", "glob"],
    "file_write": ["write_file", "edit"],
    "knowledge_retrieval": ["kg_search", "memory_search", "web_search"],
    "system_operation": ["bash"],
    "code_search": ["grep", "read_file", "glob"],
    "infrastructure": ["bash"],
    "math": ["execute_python"],
    "general": ["web_search"],
}


class DecideStage:
    """Selects tools within the constrained capability space from ActionPlan."""

    def __init__(self, llm, tool_executor, timeout_ms: int = 30_000):
        self._llm = llm
        self._tool_executor = tool_executor
        self._timeout_ms = timeout_ms
        self._tool_stats: dict[str, ToolStats] = {}

    def record_outcome(self, tool_name: str, success: bool, elapsed_ms: int = 0) -> None:
        """Record tool execution outcome for dynamic weight adjustment."""
        if tool_name not in self._tool_stats:
            self._tool_stats[tool_name] = ToolStats()
        stats = self._tool_stats[tool_name]
        stats.calls += 1
        if success:
            stats.successes += 1
        else:
            stats.failures += 1
        stats.total_latency_ms += elapsed_ms

    def get_tool_stats(self, tool_name: str) -> ToolStats | None:
        """Get statistics for a specific tool."""
        return self._tool_stats.get(tool_name)

    async def select(self, plan: ActionPlan, situation: SituationContext) -> Decision:
        allowed = self._get_allowed_tools(plan)
        available_desc = self._describe_tools(allowed)

        prompt = DECIDE_PROMPT.format(
            required_capabilities=json.dumps(plan.required_capabilities),
            strategy=plan.strategy,
            goal=plan.goal.description if plan.goal else situation.intent.raw,
            gap_analysis=plan.gap_analysis or "none",
            intent_raw=situation.intent.raw,
            available_tools=available_desc,
        )

        messages = [{"role": "user", "content": prompt}]
        try:
            response = await asyncio.wait_for(
                self._llm.chat(messages),
                timeout=self._timeout_ms / 1000.0,
            )
        except (Exception, asyncio.TimeoutError) as e:
            logger.warning(f"Decide LLM call failed: {e}, using fallback")
            return self._parse_decision("", plan, situation)

        decision = self._parse_decision(response, plan, situation)

        # Retry once if auto-selected fallback (indicates parse failure)
        if decision.primary_tool and decision.primary_tool.confidence == 0.4:
            logger.info("Decide JSON parse failed, retrying LLM call once")
            try:
                retry_response = await asyncio.wait_for(
                    self._llm.chat([
                        {"role": "user", "content": prompt},
                        {"role": "assistant", "content": response},
                        {"role": "user", "content": "Invalid JSON. Return ONLY the JSON object as specified."},
                    ]),
                    timeout=self._timeout_ms / 1000.0,
                )
                decision = self._parse_decision(retry_response, plan, situation)
            except (asyncio.TimeoutError, Exception):
                pass
        return decision

    def _get_allowed_tools(self, plan: ActionPlan) -> list[str]:
        """Get tool names allowed by the plan's required capabilities.

        Tools are sorted by dynamic success rate (best first), falling back
        to the static CAPABILITY_TOOL_MAP ordering.
        """
        allowed: set[str] = set()
        for cap in plan.required_capabilities:
            mapped = CAPABILITY_TOOL_MAP.get(cap, [])
            allowed.update(mapped)
        if not allowed:
            allowed.update(CAPABILITY_TOOL_MAP.get("general", ["web_search"]))
        # Sort by success rate (higher first), then by latency (lower first)
        return sorted(allowed, key=lambda n: (
            -self._tool_stats.get(n, ToolStats()).success_rate,
            self._tool_stats.get(n, ToolStats()).avg_latency_ms,
        ))

    def _describe_tools(self, tool_names: list[str]) -> str:
        """Describe available tools from the tool executor's registry."""
        lines = []
        try:
            all_tools = self._tool_executor.list_tools()
            tool_map = {t["name"]: t for t in all_tools}
        except Exception:
            tool_map = {}
        for name in tool_names:
            desc = tool_map.get(name, {}).get("description", "")
            lines.append(f"- {name}: {desc}")
        return "\n".join(lines) if lines else "\n".join(f"- {n}" for n in tool_names)

    def _parse_decision(self, raw: str, plan: ActionPlan, situation: SituationContext) -> Decision:
        try:
            json_str = raw.strip()
            if json_str.startswith("```"):
                json_str = json_str.split("\n", 1)[-1].rsplit("\n```", 1)[0]
            data = json.loads(json_str)
        except (json.JSONDecodeError, AttributeError):
            data = {}

        allowed = self._get_allowed_tools(plan)

        primary = self._parse_tool_binding(data.get("primary_tool", {}), allowed)
        fallback = self._parse_tool_binding(data.get("fallback_tool") or {}, allowed)
        if fallback and primary and fallback.name == primary.name:
            fallback = None  # Don't use same tool as fallback

        side_tools = [
            self._parse_tool_binding(st, allowed)
            for st in data.get("side_tools", [])
        ]

        retry = RetryPolicy(
            max_retries=data.get("retry_policy", {}).get("max_retries", 0),
            backoff=data.get("retry_policy", {}).get("backoff", 1.0),
        )

        # If primary tool is empty, pick the first allowed tool as default
        if (not primary or not primary.name) and allowed:
            primary = ToolBinding(
                name=allowed[0],
                params={"query": situation.intent.raw},
                confidence=0.4,
                reason="auto-selected (LLM failed to choose)",
            )

        return Decision(
            primary_tool=primary,
            fallback_tool=fallback,
            side_tools=side_tools,
            retry_policy=retry,
            timeout_ms=data.get("timeout_ms", 30_000),
            tool_context_prompt=data.get("tool_context_prompt", ""),
            strategy=plan.strategy,
        )

    @staticmethod
    def _parse_tool_binding(data: dict, allowed: list[str]) -> ToolBinding | None:
        if not data or not data.get("name"):
            return None
        name = data["name"]
        if name not in allowed:
            # Still use it but flag low confidence
            return ToolBinding(
                name=name,
                params=data.get("params", {}),
                confidence=min(data.get("confidence", 0.3), 0.3),
                reason=data.get("reason", "") + " (outside allowed set)",
            )
        return ToolBinding(
            name=name,
            params=data.get("params", {}),
            confidence=data.get("confidence", 0.5),
            reason=data.get("reason", ""),
        )
