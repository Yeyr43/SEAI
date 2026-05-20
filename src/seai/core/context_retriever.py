"""
SEAI 上下文检索器 — 多层上下文构建、跨会话搜索、对话配对
从 SEAgent 提取，单一职责：检索和组织上下文
"""
import re
from typing import Dict, List, Tuple, Optional
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger


class ContextRetriever:
    """上下文检索器 — 从多层记忆源构建分层上下文"""

    def __init__(self, memory_store=None, session_manager=None, knowledge_graph_manager=None):
        self.memory_store = memory_store
        self.session_manager = session_manager
        self.knowledge_graph_manager = knowledge_graph_manager

    # ── 对话配对与评分 ──────────────────────────

    @staticmethod
    def pair_conversations(messages: List[Dict]) -> List[Dict]:
        """将原始消息列表配对为完整对话轮次（user+assistant+tool 视为一轮）

        Returns:
            [{"user": "...", "assistant": "...", "tools": [...]}, ...]
        """
        pairs = []
        current = None
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "") or ""
            if role == "user":
                if current:
                    pairs.append(current)
                current = {"user": content, "assistant": "", "tools": []}
            elif role == "assistant" and current is not None:
                if current["assistant"]:
                    current["assistant"] += "\n" + content
                else:
                    current["assistant"] = content
            elif role == "tool" and current is not None:
                current["tools"].append(content)
        if current:
            pairs.append(current)
        return pairs

    @staticmethod
    def score_relevance(query: str, text: str) -> float:
        """简单但有效的关键词重叠评分（0.0 - 1.0）"""
        q_words = set(re.findall(r'[一-鿿]+|[a-zA-Z]+', query.lower()))
        t_words = set(re.findall(r'[一-鿿]+|[a-zA-Z]+', text.lower()))
        if not q_words:
            return 0.0
        overlap = q_words & t_words
        return len(overlap) / len(q_words)

    @staticmethod
    def compress_message(text: str, max_len: int = 400) -> str:
        """压缩单条消息：保留头部 + 尾部，中间截断"""
        if len(text) <= max_len:
            return text
        head_len = int(max_len * 0.55)
        tail_len = max_len - head_len
        return text[:head_len] + f"\n...[省略 {len(text) - max_len} 字符]...\n" + text[-tail_len:]

    # ── 跨会话搜索 ──────────────────────────────

    def search_cross_session_relevant(
        self, query: str, current_session_id: str = "", top_k: int = 20
    ) -> List[Dict]:
        """跨会话搜索：从全部历史会话中找出与当前查询最相关的对话轮次

        优先使用预压缩的上下文文件（ctx_{sid}.json.gz），速度快且已截断；
        若无压缩文件则回退到完整会话 JSON，并触发后台压缩保存。

        Returns:
            [{"user": "...", "assistant": "...", "score": 0.85, "session_id": "...", "session_name": "..."}, ...]
        """
        all_pairs = []
        sessions_to_compress = []
        sessions = []
        if self.session_manager:
            try:
                sessions = self.session_manager.list_sessions()
            except Exception:
                pass

        for s in sessions:
            sid = s.get("id", "")
            if sid == current_session_id:
                continue
            sname = s.get("name", "未命名")

            msgs = None
            ctx_data = self.session_manager.load_context_from_file(sid) if self.session_manager else None
            if ctx_data:
                msgs = ctx_data.get("messages", [])
            else:
                try:
                    msgs = self.session_manager.get_history(sid) if self.session_manager else None
                except Exception:
                    continue
                if msgs:
                    sessions_to_compress.append(sid)

            if not msgs:
                continue

            pairs = self.pair_conversations(msgs)
            for pair in pairs:
                combined = pair["user"] + " " + pair["assistant"]
                score = self.score_relevance(query, combined)
                if score > 0:
                    all_pairs.append({
                        "user": pair["user"],
                        "assistant": pair["assistant"],
                        "score": score,
                        "session_id": sid,
                        "session_name": sname,
                    })

        if sessions_to_compress and self.session_manager:
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    for sid in sessions_to_compress:
                        loop.create_task(
                            asyncio.to_thread(self.session_manager.save_context_to_file, sid)
                        )
            except Exception:
                pass

        all_pairs.sort(key=lambda x: x["score"], reverse=True)

        seen = set()
        deduped = []
        for p in all_pairs:
            key = p["user"][:80]
            if key not in seen:
                seen.add(key)
                deduped.append(p)
            if len(deduped) >= top_k:
                break

        return deduped

    # ── 多层上下文构建 ──────────────────────────

    def build_layered_context(self, query: str, history: List[Dict]) -> Tuple[str, str, str]:
        """四层上下文（权重分明，从高到低）

        L1 (最高权重): 当前会话最近 3 轮完整对话
        L2 (高权重):   全部历史会话中与 query 语义相关的对话轮次
        L3 (中权重):   长记忆（ChromaDB + 知识图谱 + 长期记忆存档）
        L4 (基础权重): 用户画像 + 全局知识（在 system prompt 中注入）

        Returns:
            (layer1_str, layer2_str, layer3_str)
        """
        layer1_parts = []
        layer2_parts = []
        layer3_parts = []

        # ── L1: 当前会话最近 3 轮 ──
        if history:
            pairs = self.pair_conversations(history)
            recent_pairs = pairs[-3:] if len(pairs) >= 3 else pairs
            for i, pair in enumerate(recent_pairs, 1):
                turn = []
                user_text = self.compress_message(pair['user'], max_len=300)
                turn.append(f"用户: {user_text}")
                if pair["tools"]:
                    tools_compressed = [self.compress_message(t, max_len=150) for t in pair["tools"][:3]]
                    tools_str = "; ".join(tools_compressed)
                    turn.append(f"[工具调用: {tools_str}]")
                if pair["assistant"]:
                    assistant_text = self.compress_message(pair['assistant'], max_len=500)
                    turn.append(f"SEAI: {assistant_text}")
                layer1_parts.append(f"【第{i}轮对话】\n" + "\n".join(turn))

        # ── L2: 跨会话搜索 ──
        if query:
            current_sid = ""
            if self.session_manager:
                try:
                    current_sid = self.session_manager.current_session_id
                except Exception:
                    pass

            cross_pairs = self.search_cross_session_relevant(query, current_session_id=current_sid, top_k=20)
            if cross_pairs:
                for i, cp in enumerate(cross_pairs, 1):
                    relevance = "★" if cp["score"] >= 0.5 else "☆"
                    entry = (
                        f"[{relevance} 来源: {cp['session_name']}]\n"
                        f"用户: {cp['user'][:300]}\n"
                        f"SEAI: {cp['assistant'][:300]}"
                    )
                    layer2_parts.append(entry)

        # ── L3: 长记忆 ──
        if query and self.memory_store:
            try:
                semantic_results = self.memory_store.search_memory(query, top_k=5)
                if semantic_results:
                    memorized = "\n".join(f"- {m}" for m in semantic_results if m and m.strip())
                    if memorized:
                        layer3_parts.append("## 长记忆（语义检索）\n" + memorized)
            except Exception:
                logger.warning("ChromaDB memory search failed")

            if hasattr(self.memory_store, 'get_graph_context'):
                try:
                    graph_ctx = self.memory_store.get_graph_context(query)
                    if graph_ctx:
                        layer3_parts.append("## 关联记忆（图谱）\n" + graph_ctx)
                except Exception:
                    logger.warning("Graph context retrieval failed")

            try:
                long_term = self.memory_store.get_recent_memories(limit=10)
                if long_term:
                    relevant_lt = []
                    for entry in long_term:
                        text = entry.get("text", "") or entry.get("summary", "")
                        if text and self.score_relevance(query, text) > 0.1:
                            relevant_lt.append(f"- [{entry.get('type', 'text')}] {text[:200]}")
                    if relevant_lt:
                        layer3_parts.append("## 长期记忆存档\n" + "\n".join(relevant_lt[:5]))
            except Exception:
                pass

        if self.knowledge_graph_manager and query:
            try:
                kg_context = self.knowledge_graph_manager.search(query, depth=2, top_k=5)
                if kg_context:
                    layer3_parts.append("## 知识图谱上下文\n" + kg_context)
            except Exception:
                logger.warning("Knowledge graph search failed")

        layer1_str = "\n\n".join(layer1_parts) if layer1_parts else ""
        layer2_str = "\n\n".join(layer2_parts) if layer2_parts else ""
        layer3_str = "\n\n".join(layer3_parts) if layer3_parts else ""

        return layer1_str, layer2_str, layer3_str

    # ── 辅助方法 ─────────────────────────────────

    def detect_memory_types(self, query: str) -> Optional[List[str]]:
        query_lower = query.lower()
        types = []
        if any(kw in query_lower for kw in ["代码", "bug", "函数", "报错", "code", "function", "debug"]):
            types.extend(["code", "file_snapshot"])
        if any(kw in query_lower for kw in ["网页", "链接", "搜索", "查", "search", "url"]):
            types.extend(["url", "search_result"])
        if any(kw in query_lower for kw in ["图片", "照片", "图像", "image", "photo"]):
            types.append("image_analysis")
        if any(kw in query_lower for kw in ["音频", "录音", "音乐", "声音", "audio", "voice", "speech"]):
            types.append("audio_analysis")
        return types if types else None

    def get_time_relevant_memories(self, query: str) -> str:
        if not self.memory_store:
            return ""
        try:
            now = datetime.now()
            next_week = now + timedelta(days=7)
            memories = self.memory_store.get_memories_by_timerange(
                start_time=now.isoformat(),
                end_time=next_week.isoformat(),
                limit=5
            )
            if memories:
                lines = []
                for mem in memories:
                    ts = mem.get("timestamp", "")
                    text = mem.get("text", "")[:150]
                    if ts:
                        try:
                            dt = datetime.fromisoformat(ts)
                            ts_display = dt.strftime("%m月%d日 %H:%M")
                        except Exception:
                            ts_display = ts
                        lines.append(f"- [{ts_display}] {text}")
                    else:
                        lines.append(f"- {text}")
                return "\n".join(lines)
        except Exception:
            pass
        return ""
