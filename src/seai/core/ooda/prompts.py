"""Prompt templates for OODA stages — externalized for independent tuning."""

ORIENT_PROMPT = """You are an AI execution planner. Analyze the situation and output a JSON action plan.

## Situation
- Intent: {intent_raw}
- Intent category: {intent_category}
- Intent confidence: {intent_confidence}
- Session turn: {turn_count}
- Related memories: {memory_summary}
- User profile: {user_profile}
- Last tool results: {last_tool_results}
- Context usage: {context_usage_ratio:.1%}

## Task
Determine the execution strategy and required capabilities.

## Output JSON format
{{
    "strategy": "SERIAL" | "PARALLEL" | "BID" | "FALLBACK",
    "required_capabilities": ["capability1", "capability2"],
    "gap_analysis": "one sentence describing what's missing or uncertain",
    "confidence": 0.0-1.0,
    "goal_description": "one sentence goal",
    "sub_tasks": [{{"description": "...", "capability": "..."}}],
    "estimated_tool_calls": 1-5,
    "fallback_strategy": null or "SERIAL" | "PARALLEL" | "BID" | "FALLBACK",
    "fallback_conditions": ["condition1"]
}}

Return ONLY the JSON object, no other text.
"""

# Shorter prompt for simple/low-complexity intents
ORIENT_PROMPT_SIMPLE = """You are an AI execution planner. Output a JSON action plan.

## Intent: {intent_raw}
## Last tool results: {last_tool_results}

## Output JSON
{{
    "strategy": "SERIAL" | "PARALLEL",
    "required_capabilities": ["capability1"],
    "gap_analysis": "one sentence",
    "confidence": 0.0-1.0,
    "goal_description": "one sentence goal",
    "sub_tasks": [],
    "estimated_tool_calls": 1-2,
    "fallback_strategy": null,
    "fallback_conditions": []
}}

Return ONLY the JSON object.
"""

DECIDE_PROMPT = """You are a tool selection engine. Given the required capabilities, select the best tool(s).

## Action Plan
- Required capabilities: {required_capabilities}
- Strategy: {strategy}
- Goal: {goal}
- Gap analysis: {gap_analysis}
- Original intent: {intent_raw}

## Available Tools
{available_tools}

## Output JSON
{{
    "primary_tool": {{"name": "tool_name", "params": {{...}}, "confidence": 0.0-1.0, "reason": "why"}},
    "fallback_tool": {{"name": "tool_name", "params": {{...}}, "confidence": 0.0-1.0, "reason": "why"}} or null,
    "side_tools": [{{"name": "tool_name", "params": {{...}}, "confidence": 0.0-1.0, "reason": "why"}}],
    "retry_policy": {{"max_retries": 0-3, "backoff": 0.5-2.0}},
    "timeout_ms": 10000-60000,
    "tool_context_prompt": "brief instruction for tool use context"
}}

Rules:
- primary_tool MUST be from the available tools list above
- fallback_tool should be a different tool that can partially fulfill the same capability
- Choose higher max_retries for network operations (2-3), 0 for file writes
- Return ONLY the JSON object.
"""
