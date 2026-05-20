# ══════════════════════════════════════════════════
# core/llm_manager.py - LLM 管理器（fallback + 重试 + 模型路由）
# 功能：管理多个 OpenAI 兼容端点，实现 LLMProvider 接口
#      支持自动 fallback、指数退避重试、熔断保护
#      支持按 Agent 角色分配不同 tier 的模型
# ══════════════════════════════════════════════════
import asyncio
import json
import random
from enum import Enum
from typing import List, Dict, AsyncGenerator, Union, Optional
from openai import AsyncOpenAI
import httpx
from loguru import logger
from .interfaces.llm_provider import LLMProvider
from .lazy_import import LazyImport

tiktoken_lazy = LazyImport("tiktoken", "pip install tiktoken")
from .circuit_breaker import breaker_manager


class ModelTier(str, Enum):
    """模型分层 — 不同 Agent 角色使用不同级别的模型"""
    LIGHT = "light"        # 简单任务：意图识别、分类、摘要
    STANDARD = "standard"  # 常规任务：对话、工具调用
    ENHANCED = "enhanced"  # 复杂任务：多步推理、代码生成
    PREMIUM = "premium"    # 关键任务：Commander 规划、Inspector 评估

    @classmethod
    def for_role(cls, role: str) -> "ModelTier":
        """根据 Agent 角色返回推荐的模型层级"""
        role_tier = {
            "commander": cls.PREMIUM,
            "inspector": cls.PREMIUM,
            "planner": cls.ENHANCED,
            "engineer": cls.ENHANCED,
            "code_analyzer": cls.ENHANCED,
            "code_reviewer": cls.ENHANCED,
            "test_writer": cls.ENHANCED,
            "researcher": cls.STANDARD,
            "analyst": cls.STANDARD,
            "critic": cls.STANDARD,
            "toolsmith": cls.STANDARD,
            "safety_guard": cls.STANDARD,
            "executor": cls.STANDARD,
            "communicator": cls.LIGHT,
            "memo_writer": cls.LIGHT,
            "meta_monitor": cls.LIGHT,
        }
        return role_tier.get(role, cls.STANDARD)


# Tier → 端点名称关键词映射（用于自动路由）
TIER_ENDPOINT_KEYWORDS = {
    ModelTier.LIGHT: ["mini", "flash", "haiku", "lite", "small"],
    ModelTier.STANDARD: [],
    ModelTier.ENHANCED: ["pro", "sonnet", "turbo", "qwq"],
    ModelTier.PREMIUM: ["opus", "o1", "o3", "o4", "deepseek-reasoner", "premium"],
}

RETRYABLE_ERRORS = (
    "rate_limit", "server_error", "timeout", "connection",
    "Service Unavailable", "503", "429", "overloaded",
)

MODEL_CONTEXT_LIMITS = {
    "default": 8192,
    "gpt-4": 8192, "gpt-4-turbo": 128000, "gpt-4o": 128000, "gpt-4o-mini": 128000,
    "claude-3-opus": 200000, "claude-3-sonnet": 200000, "claude-3-haiku": 200000,
    "claude-4-opus": 200000, "claude-sonnet-4": 200000,
    "deepseek-chat": 65536, "deepseek-reasoner": 65536,
    "qwen2.5": 131072, "qwen2": 131072,
    "llama3": 8192, "llama3.1": 131072, "llama3.2": 131072,
    "mistral": 32768, "mixtral": 32768,
    "gemini-pro": 32768, "gemini-1.5-pro": 1048576,
}

# 推理模型标识 (支持 reasoning_content / thinking 输出)
REASONING_MODEL_PATTERNS = (
    "deepseek-reasoner", "deepseek-r1", "o1", "o3", "o4",
    "claude-opus", "claude-4", "claude-sonnet-4",
    "qwq", "gemini-2.5-pro", "gemini-2.5-flash",
)

# 为输出保留的 token 安全余量
CONTEXT_SAFETY_MARGIN = 1024


class LLMManager(LLMProvider):
    """LLM 管理器（实现 LLMProvider 接口，含 fallback + 重试）"""

    def __init__(self, endpoints: List[Dict], max_retries: int = 3, retry_base_delay: float = 1.0):
        self.clients: Dict[str, AsyncOpenAI] = {}
        self.endpoints = endpoints
        self.current_model: str = ""
        self.max_retries = max_retries
        self.retry_base_delay = retry_base_delay
        self._model_order: List[str] = []
        self._agent_tiers: Dict[str, ModelTier] = {}  # agent_id -> ModelTier
        self._agent_token_usage: Dict[str, Dict[str, int]] = {}  # agent_id -> {model: tokens}
        self._init_clients()

    # ── Agent 模型路由 ────────────────────────────

    def register_agent(self, agent_id: str, tier: ModelTier = ModelTier.STANDARD):
        """注册 Agent 并分配模型层级"""
        self._agent_tiers[agent_id] = tier
        if agent_id not in self._agent_token_usage:
            self._agent_token_usage[agent_id] = {}

    def unregister_agent(self, agent_id: str):
        self._agent_tiers.pop(agent_id, None)

    def set_agent_tier(self, agent_id: str, tier: ModelTier):
        self._agent_tiers[agent_id] = tier

    def get_agent_tier(self, agent_id: str) -> ModelTier:
        return self._agent_tiers.get(agent_id, ModelTier.STANDARD)

    def get_agent_token_usage(self, agent_id: str = None) -> dict:
        if agent_id:
            return dict(self._agent_token_usage.get(agent_id, {}))
        return {k: dict(v) for k, v in self._agent_token_usage.items()}

    def _get_model_for_tier(self, tier: ModelTier) -> Optional[str]:
        """根据 tier 从可用端点中选择最佳模型"""
        keywords = TIER_ENDPOINT_KEYWORDS.get(tier, [])
        candidates = []
        for name in self._model_order:
            name_lower = name.lower()
            if not keywords:
                candidates.append(name)
            elif any(kw in name_lower for kw in keywords):
                candidates.append(name)
        # 返回第一个匹配的，fallback 到 current_model
        return candidates[0] if candidates else (self.current_model or None)

    def _record_token_usage(self, agent_id: str, model_id: str, messages: List[Dict]):
        """记录 Agent 的 token 使用量"""
        if agent_id not in self._agent_token_usage:
            self._agent_token_usage[agent_id] = {}
        est = self._estimate_messages_tokens(messages)
        self._agent_token_usage[agent_id][model_id] = \
            self._agent_token_usage[agent_id].get(model_id, 0) + est

    def _init_clients(self):
        self.clients.clear()
        self._model_order.clear()
        for ep in self.endpoints:
            name = ep["name"]
            self.clients[name] = AsyncOpenAI(
                api_key=ep.get("api_key", "ollama"),
                base_url=ep.get("api_base", "http://127.0.0.1:11434/v1"),
                http_client=httpx.AsyncClient(timeout=120.0)
            )
            self._model_order.append(name)
            if not self.current_model:
                self.current_model = name

    def _get_fallback_order(self) -> List[str]:
        order = list(self._model_order)
        if self.current_model in order:
            order.remove(self.current_model)
            order.insert(0, self.current_model)
        return order

    def _is_retryable(self, error: Exception) -> bool:
        msg = str(error)
        return any(sig in msg for sig in RETRYABLE_ERRORS)

    async def _retry_with_fallback(
        self, call_fn, breaker_name: str, *args, **kwargs
    ):
        last_error = None
        tried_models = []

        for model_name in self._get_fallback_order():
            if model_name in tried_models:
                continue
            tried_models.append(model_name)

            llm_breaker = breaker_manager.get_or_create(
                f"{breaker_name}_{model_name}", failure_threshold=3, cooldown_seconds=30.0
            )
            if not llm_breaker.can_execute():
                logger.warning(f"LLM [{model_name}] 熔断保护已触发，跳过")
                continue

            client = self.clients.get(model_name)
            if not client:
                continue

            model_id = self._mname_for(model_name)

            for attempt in range(self.max_retries):
                try:
                    result = await call_fn(client, model_id, *args, **kwargs)
                    llm_breaker.on_success()
                    if model_name != self.current_model:
                        logger.info(f"LLM fallback: {self.current_model} -> {model_name} 成功")
                    return result
                except Exception as e:
                    last_error = e
                    llm_breaker.on_failure()
                    if not self._is_retryable(e):
                        logger.error(f"LLM [{model_name}] 不可重试错误: {e}")
                        break
                    delay = self.retry_base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        f"LLM [{model_name}] 第{attempt+1}/{self.max_retries}次重试失败: {e}，{delay:.1f}s后重试"
                    )
                    await asyncio.sleep(delay)

        raise RuntimeError(f"所有LLM端点均已尝试失败，最后错误: {last_error}")

    def update_endpoints(self, endpoints: List[Dict]):
        self.endpoints = endpoints
        self._init_clients()

    def list_models(self) -> List[str]:
        return list(self.clients.keys())

    def add_endpoint(self, name, base, key, model):
        self.endpoints.append({"name": name, "api_base": base, "api_key": key, "model": model})
        self.clients[name] = AsyncOpenAI(api_key=key, base_url=base, http_client=httpx.AsyncClient(timeout=120.0))
        self._model_order.append(name)
        if not self.current_model:
            self.current_model = name

    def remove_endpoint(self, name):
        self.endpoints = [ep for ep in self.endpoints if ep["name"] != name]
        if name in self.clients:
            del self.clients[name]
        if name in self._model_order:
            self._model_order.remove(name)
        if self.current_model == name:
            self.current_model = next(iter(self.clients.keys()), "")

    def set_current_model(self, name):
        if name not in self.clients:
            raise ValueError(f"模型 {name} 不存在")
        self.current_model = name

    def _mname(self):
        return self._mname_for(self.current_model)

    def _mname_for(self, model_name: str) -> str:
        for ep in self.endpoints:
            if ep["name"] == model_name:
                return ep.get("model", model_name)
        return model_name

    @property
    def is_reasoning_model(self) -> bool:
        """当前模型是否为推理模型（支持 reasoning_content / thinking 输出）"""
        model_id = self._mname().lower()
        return any(pattern in model_id for pattern in REASONING_MODEL_PATTERNS)

    def _validate(self):
        if not self.current_model or self.current_model not in self.clients:
            raise RuntimeError("没有可用模型，请先添加端点。")

    # ---- Token 估算与上下文窗口管理 ----
    @staticmethod
    def _estimate_messages_tokens(messages: List[Dict]) -> int:
        """使用 tiktoken 估算消息列表的总 token 数（支持多模态 content array）"""
        if tiktoken_lazy.available:
            enc = tiktoken_lazy.get().get_encoding("cl100k_base")
            total = 0
            for msg in messages:
                content = msg.get("content", "")
                if isinstance(content, str):
                    total += len(enc.encode(content))
                elif isinstance(content, list):
                    for block in content:
                        if block.get("type") == "text":
                            total += len(enc.encode(block.get("text", "")))
                        elif block.get("type") == "image_url":
                            total += 258  # 标准 detail:auto 固定开销
                role = msg.get("role", "")
                total += len(enc.encode(role)) if role else 0
                total += 4  # per-message overhead
            total += 2  # reply overhead
            return total
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content) // 2
            elif isinstance(content, list):
                for block in content:
                    if block.get("type") == "text":
                        total += len(block.get("text", "")) // 2
                    elif block.get("type") == "image_url":
                        total += 258
        return total

    def _get_context_limit(self) -> int:
        """获取当前模型的上下文窗口大小"""
        model_id = self._mname().lower()
        for key, limit in MODEL_CONTEXT_LIMITS.items():
            if key in model_id:
                return limit
        return MODEL_CONTEXT_LIMITS["default"]

    def _truncate_messages(self, messages: List[Dict]) -> List[Dict]:
        """如果消息总 token 超出上下文窗口，从历史中丢弃最早的非 system 消息。
        保证 tool/tool_calls 配对完整，避免 API 400 错误。"""
        limit = self._get_context_limit()
        estimated = self._estimate_messages_tokens(messages)
        if estimated <= limit - CONTEXT_SAFETY_MARGIN:
            return messages

        logger.warning(
            f"消息超长: {estimated} tokens (模型窗口: {limit}), "
            f"将截断最早的 {estimated - (limit - CONTEXT_SAFETY_MARGIN)} tokens"
        )

        system_msgs = [m for m in messages if m.get("role") == "system"]
        history_msgs = [m for m in messages if m.get("role") != "system"]

        while history_msgs and self._estimate_messages_tokens(system_msgs + history_msgs) > limit - CONTEXT_SAFETY_MARGIN:
            removed = history_msgs.pop(0)
            removed_role = removed.get("role", "")

            # 移除 assistant+tool_calls 时，连带移除后续 tool 响应消息
            if removed_role == "assistant" and removed.get("tool_calls"):
                removed_ids = {tc.get("id", "") for tc in removed.get("tool_calls", [])}
                while history_msgs and history_msgs[0].get("role") == "tool":
                    if history_msgs[0].get("tool_call_id", "") in removed_ids:
                        history_msgs.pop(0)
                    else:
                        break

            # 移除 tool 消息时，沿后续继续移除同一轮的 tool 消息
            elif removed_role == "tool":
                while history_msgs and history_msgs[0].get("role") == "tool":
                    history_msgs.pop(0)

        return system_msgs + history_msgs

    # ── 同步对话 ──────────────────────────────────
    async def chat(self, messages, agent_id: str = None):
        self._validate()
        messages = self._truncate_messages(messages)

        old_model = None
        if agent_id:
            tier = self.get_agent_tier(agent_id)
            tier_model = self._get_model_for_tier(tier)
            if tier_model and tier_model != self.current_model:
                old_model = self.current_model
                self.current_model = tier_model
                logger.debug(f"Agent [{agent_id}] tier={tier.value} → 路由到模型 {tier_model}")

        async def _call(client, model_id, msgs):
            r = await client.chat.completions.create(model=model_id, messages=msgs)
            return r.choices[0].message.content

        try:
            result = await self._retry_with_fallback(_call, "llm_chat", messages)
            if agent_id:
                self._record_token_usage(agent_id, self._mname(), messages)
            return result
        finally:
            if old_model is not None:
                self.current_model = old_model

    # ---- 流式对话 ----
    async def chat_stream(self, messages: List[Dict]) -> AsyncGenerator[str, None]:
        self._validate()
        messages = self._truncate_messages(messages)
        tried_models = []

        for model_name in self._get_fallback_order():
            if model_name in tried_models:
                continue
            tried_models.append(model_name)

            llm_breaker = breaker_manager.get_or_create(
                f"llm_stream_{model_name}", failure_threshold=3, cooldown_seconds=30.0
            )
            if not llm_breaker.can_execute():
                continue

            client = self.clients.get(model_name)
            if not client:
                continue
            model_id = self._mname_for(model_name)

            for attempt in range(self.max_retries):
                try:
                    response = await client.chat.completions.create(
                        model=model_id, messages=messages, stream=True
                    )
                    reasoning_buffer = []
                    reasoning_started = False
                    async for chunk in response:
                        delta = chunk.choices[0].delta
                        # 推理模型的 thinking/reasoning 内容
                        reasoning = getattr(delta, "reasoning_content", None) or getattr(delta, "thinking", None)
                        if reasoning:
                            if not reasoning_started:
                                yield "\n[THINK]"
                                reasoning_started = True
                            reasoning_buffer.append(reasoning)
                            yield reasoning
                        if delta.content:
                            if reasoning_started and reasoning_buffer:
                                yield "[/THINK]\n"
                                reasoning_started = False
                            yield delta.content
                    if reasoning_started:
                        yield "[/THINK]\n"
                    llm_breaker.on_success()
                    return
                except Exception as e:
                    llm_breaker.on_failure()
                    if not self._is_retryable(e):
                        break
                    delay = self.retry_base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    await asyncio.sleep(delay)

        yield "所有LLM端点均已尝试失败，请检查网络连接和API配置。"

    # ── 工具调用 ──────────────────────────────────
    def chat_with_tools(self, messages, tools, stream=False, agent_id: str = None):
        if stream:
            return self._chat_with_tools_stream(messages, tools, agent_id=agent_id)
        return self._chat_with_tools_sync(messages, tools, agent_id=agent_id)

    async def _chat_with_tools_sync(self, messages, tools, agent_id: str = None):
        self._validate()
        messages = self._truncate_messages(messages)

        old_model = None
        if agent_id:
            tier = self.get_agent_tier(agent_id)
            tier_model = self._get_model_for_tier(tier)
            if tier_model and tier_model != self.current_model:
                old_model = self.current_model
                self.current_model = tier_model

        async def _call(client, model_id, msgs, tls):
            r = await client.chat.completions.create(
                model=model_id, messages=msgs, tools=tls, tool_choice="auto", stream=False
            )
            msg = r.choices[0].message
            if msg.tool_calls:
                return {
                    "tool_calls": [
                        {
                            "id": t.id, "type": "function",
                            "function": {"name": t.function.name, "arguments": t.function.arguments}
                        }
                        for t in msg.tool_calls
                    ],
                    "reasoning_content": getattr(msg, "reasoning_content", None),
                    "content": msg.content,
                }
            return msg.content

        try:
            result = await self._retry_with_fallback(_call, "llm_tools", messages, tools)
            if agent_id:
                self._record_token_usage(agent_id, self._mname(), messages)
            return result
        finally:
            if old_model is not None:
                self.current_model = old_model

    async def _chat_with_tools_stream(self, messages, tools, agent_id: str = None):
        self._validate()
        messages = self._truncate_messages(messages)
        tried_models = []

        # Agent 路由：优先使用 tier 对应的模型
        fallback_order = self._get_fallback_order()
        if agent_id:
            tier = self.get_agent_tier(agent_id)
            tier_model = self._get_model_for_tier(tier)
            if tier_model and tier_model in fallback_order:
                fallback_order.remove(tier_model)
                fallback_order.insert(0, tier_model)

        for model_name in fallback_order:
            if model_name in tried_models:
                continue
            tried_models.append(model_name)

            llm_breaker = breaker_manager.get_or_create(
                f"llm_tools_stream_{model_name}", failure_threshold=3, cooldown_seconds=30.0
            )
            if not llm_breaker.can_execute():
                continue

            client = self.clients.get(model_name)
            if not client:
                continue
            model_id = self._mname_for(model_name)

            for attempt in range(self.max_retries):
                try:
                    s = await client.chat.completions.create(
                        model=model_id, messages=messages, tools=tools,
                        stream=True
                    )
                    tool_calls_acc = {}
                    async for chunk in s:
                        delta = chunk.choices[0].delta
                        if delta.content:
                            yield delta.content
                        if delta.tool_calls:
                            for tc_delta in delta.tool_calls:
                                idx = tc_delta.index
                                if idx not in tool_calls_acc:
                                    tool_calls_acc[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                if tc_delta.id:
                                    tool_calls_acc[idx]["id"] = tc_delta.id
                                if tc_delta.function:
                                    if tc_delta.function.name:
                                        tool_calls_acc[idx]["function"]["name"] = tc_delta.function.name
                                    if tc_delta.function.arguments:
                                        tool_calls_acc[idx]["function"]["arguments"] += tc_delta.function.arguments
                    # 如果检测到工具调用，以 JSON 形式 yield 供上游处理
                    if tool_calls_acc:
                        yield f"\n__TOOL_CALLS__{json.dumps(list(tool_calls_acc.values()))}__/TOOL_CALLS__\n"
                    llm_breaker.on_success()
                    if agent_id:
                        self._record_token_usage(agent_id, model_id, messages)
                    return
                except Exception as e:
                    llm_breaker.on_failure()
                    if not self._is_retryable(e):
                        logger.error(f"LLM [{model_name}] 流式工具调用不可重试错误: {e}")
                        break
                    delay = self.retry_base_delay * (2 ** attempt) + random.uniform(0, 0.5)
                    logger.warning(
                        f"LLM [{model_name}] 流式第{attempt+1}/{self.max_retries}次重试失败: {e}，{delay:.1f}s后重试"
                    )
                    await asyncio.sleep(delay)

        logger.error("所有LLM流式端点均已尝试失败，回退到同步 tool_loop")
        yield "所有LLM端点均已尝试失败，请检查网络连接和API配置。"

    # ---- 接口方法 ----
    def get_available_models(self) -> List[str]:
        return list(self.clients.keys())

    def get_current_model(self) -> str:
        return self.current_model