"""
SEAI 上下文管理器 — 监控上下文窗口使用量，自动压缩和持久化

功能：
- 监控 Token 使用量，80% 阈值时触发压缩
- 压缩历史对话为结构化摘要
- 支持任务状态挂起/恢复
"""
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from loguru import logger


@dataclass
class CompressedContext:
    """压缩后的上下文摘要"""
    task_goal: str = ""
    key_decisions: list = field(default_factory=list)
    completed_items: list = field(default_factory=list)
    pending_items: list = field(default_factory=list)
    important_artifacts: list = field(default_factory=list)
    original_message_count: int = 0
    compressed_message_count: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_prompt(self) -> str:
        parts = [f"## 上下文摘要（原 {self.original_message_count} 条消息，压缩后 {self.compressed_message_count} 条）\n"]
        if self.task_goal:
            parts.append(f"### 任务目标\n{self.task_goal}\n")
        if self.key_decisions:
            parts.append("### 关键决策\n- " + "\n- ".join(self.key_decisions) + "\n")
        if self.completed_items:
            parts.append("### 已完成\n- " + "\n- ".join(self.completed_items) + "\n")
        if self.pending_items:
            parts.append("### 待处理\n- " + "\n- ".join(self.pending_items) + "\n")
        if self.important_artifacts:
            parts.append("### 重要产出\n- " + "\n- ".join(self.important_artifacts) + "\n")
        return "\n".join(parts)


class ContextManager:
    """上下文管理器 — 监控、压缩、持久化"""

    def __init__(self, max_tokens: int = 128000, compress_threshold: float = 0.8,
                 llm_provider=None, memory_store=None):
        self.max_tokens = max_tokens
        self.compress_threshold = compress_threshold
        self.llm_provider = llm_provider
        self.memory_store = memory_store
        self._current_tokens = 0
        self._task_state: Dict[str, Any] = {}
        self._compression_count = 0

    def estimate_tokens(self, messages: List[Dict]) -> int:
        """快速估算消息的 token 数"""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content) // 2  # 粗略估算：~2 chars/token
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict):
                        total += len(str(block.get("text", ""))) // 2
            total += 4  # per-message overhead
        self._current_tokens = total
        return total

    def is_near_limit(self, messages: List[Dict]) -> bool:
        """检查是否接近上下文窗口限制"""
        tokens = self.estimate_tokens(messages)
        return tokens > self.max_tokens * self.compress_threshold

    def usage_ratio(self, messages: List[Dict]) -> float:
        return self.estimate_tokens(messages) / self.max_tokens

    async def compress(self, messages: List[Dict], task_goal: str = "") -> CompressedContext:
        """压缩历史对话为结构化摘要。使用 LLM 提取关键信息。"""
        extracted = self._rule_based_extract(messages)
        extracted.task_goal = task_goal or extracted.task_goal

        # 如果有 LLM，用 LLM 增强压缩质量
        if self.llm_provider:
            try:
                enhanced = await self._llm_compress(messages, extracted)
                if enhanced:
                    extracted = enhanced
            except Exception:
                pass

        self._compression_count += 1

        # 将压缩前的完整历史保存到记忆系统
        if self.memory_store and hasattr(self.memory_store, 'add_long_term_memory_with_links'):
            try:
                self.memory_store.add_long_term_memory_with_links(
                    f"[上下文压缩 #{self._compression_count}] {extracted.task_goal[:200]}",
                    mem_type="context_snapshot",
                    storage_mode="summary"
                )
            except Exception:
                pass

        logger.info(f"上下文压缩完成 [#{self._compression_count}]: "
                    f"{extracted.original_message_count} → {extracted.compressed_message_count}")
        return extracted

    def _rule_based_extract(self, messages: List[Dict]) -> CompressedContext:
        """基于规则从消息中提取关键信息"""
        ctx = CompressedContext(original_message_count=len(messages))

        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if isinstance(content, list):
                content = " ".join(
                    b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
                )
            if not isinstance(content, str) or not content.strip():
                continue

            # 提取任务目标（首个 user 消息）
            if role == "user" and not ctx.task_goal and len(content) > 10:
                ctx.task_goal = content[:200]

            # 提取决策（system 或 assistant 中的关键标记）
            if role in ("assistant", "system"):
                if any(kw in content for kw in ("决定", "decision", "结论", "conclusion", "方案", "plan")):
                    ctx.key_decisions.append(content[:300])

            # 提取工具调用结果（appended as artifacts）
            if role == "user" and content.startswith("[工具"):
                ctx.important_artifacts.append(content[:500])

            # 跟踪完成/待办
            if "DONE" in content or "完成" in content or "completed" in content.lower():
                ctx.completed_items.append(content[:200])

        ctx.compressed_message_count = (
            (1 if ctx.task_goal else 0) +
            min(len(ctx.key_decisions), 5) +
            min(len(ctx.completed_items), 5) +
            min(len(ctx.important_artifacts), 3)
        )
        return ctx

    async def _llm_compress(self, messages: List[Dict], base: CompressedContext) -> Optional[CompressedContext]:
        """使用 LLM 进行更精确的压缩（轻量摘要）"""
        if not self.llm_provider:
            return None

        # 只取最近的消息来压缩（避免递归压缩导致无限循环）
        recent_msgs = messages[-30:] if len(messages) > 30 else messages
        prompt = (
            "请将以下对话压缩为结构化摘要，只提取关键信息。输出 JSON 格式：\n"
            '{"task_goal": "任务目标", "key_decisions": ["决策1", "决策2"], '
            '"completed_items": ["已完成1"], "pending_items": ["待处理1"], '
            '"important_artifacts": ["产出1"]}\n\n'
            "对话内容：\n"
        )
        for msg in recent_msgs:
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                prompt += f"[{msg.get('role', '?')}] {content[:300]}\n"

        try:
            response = await self.llm_provider.chat([{"role": "user", "content": prompt}])
            import json
            data = json.loads(response) if isinstance(response, str) else response
            if isinstance(data, dict):
                base.task_goal = data.get("task_goal", base.task_goal)
                base.key_decisions = data.get("key_decisions", base.key_decisions)
                base.completed_items = data.get("completed_items", base.completed_items)
                base.pending_items = data.get("pending_items", base.pending_items)
                base.important_artifacts = data.get("important_artifacts", base.important_artifacts)
            return base
        except Exception:
            return None

    # ── 任务状态持久化 ────────────────────────────

    def save_task_state(self, task_id: str, state: Dict[str, Any]):
        self._task_state[task_id] = {
            "state": state,
            "saved_at": time.time(),
        }

    def load_task_state(self, task_id: str) -> Optional[Dict[str, Any]]:
        entry = self._task_state.get(task_id)
        return entry["state"] if entry else None

    def get_stats(self) -> dict:
        return {
            "current_tokens": self._current_tokens,
            "usage_ratio": self._current_tokens / self.max_tokens if self.max_tokens else 0,
            "compression_count": self._compression_count,
            "saved_tasks": len(self._task_state),
        }
