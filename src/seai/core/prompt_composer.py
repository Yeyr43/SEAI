"""
SEAI 提示词组装器 — 系统提示词构建、自检协议、Token 估算
从 SEAgent 提取，单一职责：组装和缓存提示词
"""
from typing import Dict, List, Optional
from .lazy_import import LazyImport

tiktoken_lazy = LazyImport("tiktoken", "pip install tiktoken")


class PromptComposer:
    """提示词组装器 — 构建静态系统提示词（缓存） + 动态部分"""

    def __init__(self, prompt_engine=None, memory_store=None):
        self._prompt_engine = prompt_engine
        self._memory_store = memory_store
        self._static_prompt_cache: Dict[str, str] = {}

    def build_static_system_prompt(
        self,
        locale: str = "zh-CN",
        thinking_enabled: bool = True,
        web_search_enabled: bool = False,
    ) -> str:
        """构建系统提示词（静态部分缓存 + 动态部分实时读取）"""
        cache_key = f"{locale}:{thinking_enabled}:{web_search_enabled}"
        cached = self._static_prompt_cache.get(cache_key)
        if cached is None:
            parts = []

            if self._prompt_engine:
                parts.append(self._prompt_engine.get_core_identity(locale))
            else:
                parts.append("""你是 SEAI 智能体，可以读取本地文件、在特定目录写入、生成技能并自我进化。

## 核心能力
1. 文件操作：读取、写入、删除文件
2. 技能执行：执行预定义的技能包
3. 联网搜索：获取实时信息
4. 命令执行：运行系统命令
5. 自我进化：通过反思改进自身能力

## 工具使用规则（必须遵守）
- 需要进行文件操作、命令执行、联网搜索时，必须直接调用对应的工具函数
- 不要只描述你打算做什么，必须实际调用工具函数来完成操作
- 工具调用完成后，基于返回结果用文字回答用户
- 回答要清晰、准确、有帮助
""")

            if thinking_enabled:
                if self._prompt_engine:
                    thinking = self._prompt_engine.get_thinking_protocol(locale)
                    if thinking:
                        parts.append(thinking)
                else:
                    parts.append("## 深度思考模式\n在回答前输出 [THINK]你的分析[/THINK]")

            if web_search_enabled:
                parts.append("【联网搜索已启用】")

            self._static_prompt_cache[cache_key] = "\n\n".join(parts)

        # 动态部分：用户画像 + 全局知识
        dynamic_parts = []
        if self._memory_store:
            try:
                user_profile = self._memory_store.get_user_profile()
                if user_profile:
                    dynamic_parts.append("## 用户画像（基础权重 ∎ — 长期特征）\n" + user_profile)
            except Exception:
                pass

            try:
                global_knowledge = self._memory_store.get_global_knowledge()
                if global_knowledge:
                    dynamic_parts.append("## 全局知识（基础权重 ∎ — 累积知识）\n" + global_knowledge)
            except Exception:
                pass

        result = self._static_prompt_cache[cache_key]
        if dynamic_parts:
            result = result + "\n\n" + "\n\n".join(dynamic_parts)
        return result

    def invalidate_cache(self):
        self._static_prompt_cache.clear()

    def build_self_check(self, query: str, locale: str = "zh-CN") -> str:
        parts = []
        if self._prompt_engine:
            core = self._prompt_engine.get_core_identity(locale)
            if core:
                parts.append(core)
            check = self._prompt_engine.get_check_prompt(locale)
            if check:
                parts.append(check)
        parts.append(query)
        return "\n\n".join(parts)

    @staticmethod
    def estimate_text_tokens(text: str) -> int:
        """使用 tiktoken 精确估算单段文本 token 数"""
        if not text:
            return 0
        if tiktoken_lazy.available:
            return len(tiktoken_lazy.get().get_encoding("cl100k_base").encode(text))
        return len(text) // 2

    @staticmethod
    def estimate_tokens_fallback(messages: List[Dict]) -> int:
        """兜底 token 估算（无 LLM 管理器时）"""
        if tiktoken_lazy.available:
            encoding = tiktoken_lazy.get().get_encoding("cl100k_base")
            total = 0
            for msg in messages:
                content = msg.get("content", "")
                if isinstance(content, str):
                    total += len(encoding.encode(content))
                elif isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict):
                            if block.get("type") == "text":
                                total += len(encoding.encode(block.get("text", "")))
                            elif block.get("type") == "image_url":
                                total += 258
                role = msg.get("role", "")
                total += len(encoding.encode(role))
                total += 4
            total += 2
            return total
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, str):
                total += len(content) // 2
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        total += len(block.get("text", "")) // 2
                    elif isinstance(block, dict) and block.get("type") == "image_url":
                        total += 258
        return total
