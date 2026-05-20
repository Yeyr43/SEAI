""""""
from loguru import logger
from typing import AsyncGenerator
from typing import Dict
from typing import List
import asyncio
import json
import sys

class SessionMixin:
    async def chat(self, query: str, thinking_enabled: bool = True, web_search: bool = False, session_id: str = "") -> str:
        history = self._load_session_history(session_id)
        result = []
        async for chunk in self.process_query(query, history=history, thinking_enabled=thinking_enabled, web_search=web_search):
            result.append(chunk)
        reply = "".join(result)
        self._save_chat_message(session_id, query, reply)
        return reply

    async def chat_stream(self, query: str, thinking_enabled: bool = True, web_search: bool = False, session_id: str = "") -> AsyncGenerator[str, None]:
        history = self._load_session_history(session_id)
        full_response = []
        async for chunk in self.process_query(query, history=history, stream=True, thinking_enabled=thinking_enabled, web_search=web_search):
            full_response.append(chunk)
            yield chunk
        reply = "".join(full_response)
        self._save_chat_message(session_id, query, reply, use_tiktoken=False)

    def new_session(self) -> str:
        return self._conversation_service.new_session() if self._conversation_service else self.session_manager.create_session()

    def switch_session(self, session_id: str):
        if self._conversation_service:
            self._conversation_service.switch_session(session_id)
        else:
            self.session_manager.switch_session(session_id)
        self.current_session_id = session_id

    def delete_session(self, session_id: str):
        if self._conversation_service:
            self._conversation_service.delete_session(session_id)
        else:
            self.session_manager.delete_session(session_id)

    async def generate_title(self, session_id: str) -> str:
        if self._conversation_service:
            return await self._conversation_service.generate_title(session_id)
        history = self.session_manager.get_history(session_id)
        if not history:
            return "新对话"
        if self.llm_provider:
            try:
                msgs = [{"role": "system", "content": "为以下对话生成一个简短标题（10字以内），只输出标题。"},
                        {"role": "user", "content": "\n".join([m.get("content", "")[:100] for m in history[-4:]])}]
                title = await self.llm_provider.chat(msgs)
                return title.strip()[:20] if title else "未命名"
            except Exception:
                logger.warning("Title generation failed")
        return "未命名"

    async def export_current_session(self, format: str = "markdown") -> str:
        if self._conversation_service:
            return await self._conversation_service.export_session(
                self._conversation_service.get_current_session_id(), format
            )
        history = self.session_manager.get_current_history()
        if format == "markdown":
            lines = ["# SEAI 对话记录\n"]
            for msg in history:
                role = "**用户**" if msg["role"] == "user" else "**SEAI**"
                lines.append(f"{role}:\n{msg['content']}\n")
            return "\n".join(lines)
        return json.dumps(history, indent=2, ensure_ascii=False)

    def _load_session_history(self, session_id: str) -> List[Dict]:
        if self._conversation_service:
            return self._conversation_service.load_history(session_id)
        if not session_id:
            return []
        try:
            return self.session_manager.get_history(session_id)
        except Exception:
            logger.warning("Session history load failed"); return []

    def _save_chat_message(self, session_id: str, query: str, reply: str, use_tiktoken: bool = True):
        if use_tiktoken and tiktoken_lazy.available:
            try:
                enc = tiktoken_lazy.get().get_encoding("cl100k_base")
                token_count = len(enc.encode(query + reply))
            except Exception:
                token_count = (len(query) + len(reply)) // 2
        else:
            token_count = (len(query) + len(reply)) // 2

        if self._conversation_service:
            self._conversation_service.save_message(session_id, "user", query, token_count)
            self._conversation_service.save_message(session_id, "assistant", reply, token_count)
            return
        if not session_id or not reply:
            return
        try:
            self.session_manager.add_message("user", query)
            self.session_manager.add_message("assistant", reply)
            self._save_context_async(session_id)
        except Exception:
            logger.warning("Save chat message failed")

    def _save_context_async(self, session_id: str):
        """后台保存压缩上下文文件（每个会话独立存储，非阻塞）"""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(
                    asyncio.to_thread(self.session_manager.save_context_to_file, session_id)
                )
            else:
                self.session_manager.save_context_to_file(session_id)
        except Exception:
            logger.warning("Save context failed")
