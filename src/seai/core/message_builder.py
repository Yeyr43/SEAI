"""
Message Builder — 从 SEAgent 提取的消息构建逻辑
职责：构建 LLM 消息列表、系统提示词、分层上下文、多模态内容注入
"""
import re
import os as _os
import time
import uuid
from typing import List, Dict, Optional
from pathlib import Path
from loguru import logger

from .lazy_import import LazyImport

tiktoken_lazy = LazyImport("tiktoken", "pip install tiktoken")

IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
AUDIO_EXTS = {'.wav', '.mp3', '.ogg', '.flac', '.m4a'}
MIME_MAP = {
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
    '.png': 'image/png', '.gif': 'image/gif',
    '.webp': 'image/webp', '.bmp': 'image/bmp',
}


class MessageBuilder:
    """构建 LLM 输入消息，管理系统提示词、上下文分层、多模态内容"""

    def __init__(self, llm_provider=None, memory_store=None, prompt_engine=None,
                 kg_provider=None, skill_repository=None, config=None):
        self.llm_provider = llm_provider
        self.memory_store = memory_store
        self.prompt_engine = prompt_engine
        self.kg_provider = kg_provider
        self.skill_repository = skill_repository
        self.config = config
        self._static_prompt_cache: Dict[str, str] = {}
        self._self_check_context: str = ""

    def set_self_check_context(self, context: str):
        self._self_check_context = context

    def estimate_text_tokens(self, text: str) -> int:
        if not text:
            return 0
        if tiktoken_lazy.available:
            return len(tiktoken_lazy.get().get_encoding("cl100k_base").encode(text))
        return len(text) // 2

    def build_static_system_prompt(self, locale: str = "zh", thinking_enabled: bool = True,
                                   web_search_enabled: bool = False) -> str:
        cache_key = f"{locale}:{thinking_enabled}:{web_search_enabled}"
        cached = self._static_prompt_cache.get(cache_key)
        if cached is not None:
            return cached

        parts = []
        if self.prompt_engine:
            core = self.prompt_engine.get_core_identity(locale)
            if core:
                parts.append(core)
            tools_prompt = self.prompt_engine.get_tools_prompt(locale)
            if tools_prompt:
                parts.append(tools_prompt)
            pua = self.prompt_engine.get_pua_prompt(locale)
            if pua:
                parts.append(pua)

        if not parts:
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
            if self.prompt_engine:
                thinking = self.prompt_engine.get_thinking_protocol(locale)
                if thinking:
                    parts.append(thinking)
            if not any("思考" in p for p in parts):
                parts.append("## 深度思考模式\n在回答前输出 [THINK]你的分析[/THINK]")

        if web_search_enabled:
            parts.append("【联网搜索已启用】你可以使用 web_search 工具搜索实时信息。")

        result = "\n\n".join(parts)
        self._static_prompt_cache[cache_key] = result
        return result

    def invalidate_prompt_cache(self):
        self._static_prompt_cache.clear()

    def build_self_check(self, query: str, locale: str = "zh") -> str:
        parts = []
        if self.prompt_engine:
            core = self.prompt_engine.get_core_identity(locale)
            if core:
                parts.append(core)
            check = self.prompt_engine.get_check_prompt(locale)
            if check:
                parts.append(check)
        parts.append(query)
        return "\n\n".join(parts)

    def build_layered_context(self, query: str, history: List[Dict]) -> tuple:
        L1_COUNT = 3
        L2_MIN = 2
        L2_BUDGET = 1500
        L3_BUDGET = 3000

        layer1 = ""
        layer2 = ""
        layer3 = ""

        if history:
            recent = history[-L1_COUNT:]
            layer1 = "\n".join(
                f"{'用户' if m.get('role') == 'user' else 'SEAI'}: {m.get('content', '')[:500]}"
                for m in recent
            )

            l2_parts = []
            l2_tokens = 0
            l2_count = 0
            for m in reversed(history[:-L1_COUNT]):
                role_label = '用户' if m.get('role') == 'user' else 'SEAI'
                content = m.get('content', '')
                tokens = self.estimate_text_tokens(content)
                if l2_tokens + tokens > L2_BUDGET and l2_count >= L2_MIN:
                    break
                l2_parts.append(f"{role_label}: {content[:300]}")
                l2_tokens += tokens
                l2_count += 1
            if l2_parts:
                layer2 = "\n".join(reversed(l2_parts))

        try:
            if self.memory_store:
                mems = self.memory_store.search(query, top_k=5)
                if mems:
                    layer3 = "\n".join(m[:200] for m in mems[:5])
        except Exception:
            logger.warning("Memory search failed")

        if not layer3 and self.kg_provider:
            try:
                kg_context = self.kg_provider.search(query)
                if kg_context:
                    layer3 = kg_context[:L3_BUDGET]
            except Exception:
                logger.warning("Knowledge graph search failed")

        return layer1, layer2, layer3

    def get_media_blocks_for_query(self, query: str) -> list:
        if not self.memory_store:
            return []
        media_keywords = ["图片", "照片", "图像", "音频", "录音", "音乐", "之前发的", "刚才的",
                          "image", "photo", "picture", "audio", "media"]
        if not any(kw in query.lower() for kw in media_keywords):
            return []
        try:
            media_memories = self.memory_store.search_by_type(
                query, ["image_analysis", "audio_analysis"], top_k=3
            )
            blocks = []
            for mem in media_memories:
                media_id = mem.get("media_id") if isinstance(mem, dict) else None
                if not media_id:
                    continue
                media_b64 = self.memory_store.get_media(media_id)
                if media_b64:
                    blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{media_b64}"}
                    })
            return blocks
        except Exception:
            return []

    def auto_encode_media_paths(self, query: str, memory_store=None) -> list:
        from se_tool import encode_image_to_base64

        store = memory_store or self.memory_store

        all_exts = IMAGE_EXTS | AUDIO_EXTS
        ext_group = '|'.join(re.escape(e.lstrip('.')) for e in all_exts)

        quoted_p = re.compile(r'[\'"]([^\'"]+\.(?:' + ext_group + r'))[\'"]', re.IGNORECASE)
        bare_p = re.compile(r'(?:^|\s)([^\s\'"]+\.(?:' + ext_group + r'))(?:\s|$)', re.IGNORECASE)
        drive_p = re.compile(r'([A-Za-z]:[\\/][^\s\'"]*\.(?:' + ext_group + r'))', re.IGNORECASE)

        candidates = []
        for m in quoted_p.finditer(query):
            candidates.append(m.group(1))
        for m in bare_p.finditer(query):
            candidates.append(m.group(1))
        for m in drive_p.finditer(query):
            candidates.append(m.group(1))

        blocks = []
        processed = set()

        for raw_path in candidates:
            path = _os.path.normpath(raw_path.strip('\'"'))
            if path in processed or not _os.path.isfile(path):
                continue
            processed.add(path)

            ext = _os.path.splitext(path)[1].lower()

            if ext in IMAGE_EXTS:
                b64 = encode_image_to_base64(path)
                if b64:
                    mime = MIME_MAP.get(ext, 'image/jpeg')
                    blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"}
                    })
                    if store and hasattr(store, 'store_media'):
                        media_id = uuid.uuid4().hex[:12]
                        store.store_media(
                            media_id, "image_analysis", b64,
                            {"tool": "auto_encode", "path": path, "timestamp": time.time()}
                        )
                        if hasattr(store, 'add_long_term_memory_with_links'):
                            store.add_long_term_memory_with_links(
                                f"[auto_encode] {path} → 自动编码分析",
                                mem_type="image_analysis", storage_mode="original",
                                media_id=media_id
                            )
            elif ext in AUDIO_EXTS:
                from se_tool import encode_audio_to_base64
                b64 = encode_audio_to_base64(path)
                if b64 and store and hasattr(store, 'store_media'):
                    media_id = uuid.uuid4().hex[:12]
                    store.store_media(
                        media_id, "audio_analysis", b64,
                        {"tool": "auto_encode", "path": path, "timestamp": time.time()}
                    )
                    if hasattr(store, 'add_long_term_memory_with_links'):
                        store.add_long_term_memory_with_links(
                            f"[auto_encode] {path} → 已编码音频并存储",
                            mem_type="audio_analysis", storage_mode="original",
                            media_id=media_id
                        )
        return blocks

    def estimate_messages_tokens(self, messages: List[Dict]) -> int:
        if self.llm_provider and hasattr(self.llm_provider, '_estimate_messages_tokens'):
            return self.llm_provider._estimate_messages_tokens(messages)

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

    def build_messages(self, query: str, history: List[Dict], locale: str = "zh",
                       thinking_enabled: bool = True, web_search_enabled: bool = False) -> List[Dict]:
        messages = []

        system_prompt = self.build_static_system_prompt(locale, thinking_enabled, web_search_enabled)
        if self._self_check_context:
            system_prompt = self._self_check_context + "\n\n---\n\n" + system_prompt
        messages.append({"role": "system", "content": system_prompt})

        layer1, layer2, layer3 = self.build_layered_context(query, history)

        context_parts = []
        if layer1:
            context_parts.append("## 当前会话最近对话（最高权重 - 必须优先参考）\n" + layer1)
        if layer2:
            context_parts.append("## 历史相关对话（高权重 - 全部会话检索）\n" + layer2)
        if layer3:
            context_parts.append("## 长记忆与知识库（中权重 - 背景参考）\n" + layer3)

        if context_parts:
            messages.append({"role": "system", "content": "\n\n".join(context_parts)})

        media_blocks = self.get_media_blocks_for_query(query)
        auto_blocks = self.auto_encode_media_paths(query)

        all_blocks = media_blocks + auto_blocks
        if all_blocks:
            content_array = [{"type": "text", "text": query}]
            content_array.extend(all_blocks)
            messages.append({"role": "user", "content": content_array})
        else:
            messages.append({"role": "user", "content": query})

        return messages
