"""
SEAI 对话服务 - 从 SEAgent 中提取的会话管理逻辑
负责会话生命周期、历史管理、标题生成、导出
"""
import json
import time
from typing import Dict, List, Optional, AsyncGenerator
from pathlib import Path
from loguru import logger


class ConversationService:
    """对话服务 - 管理会话生命周期和历史记录"""

    def __init__(self, session_manager, llm_provider=None, data_dir: Path = None):
        self.session_manager = session_manager
        self.llm_provider = llm_provider
        self.data_dir = data_dir

    def new_session(self, first_message: str = "") -> str:
        return self.session_manager.create_session(first_message)

    def switch_session(self, session_id: str):
        self.session_manager.switch_session(session_id)

    def delete_session(self, session_id: str):
        self.session_manager.delete_session(session_id)

    def get_current_session_id(self) -> str:
        return getattr(self.session_manager, 'current_session_id', '')

    def list_sessions(self) -> List[Dict]:
        return self.session_manager.list_sessions() if hasattr(self.session_manager, 'list_sessions') else []

    async def generate_title(self, session_id: str) -> str:
        history = self.session_manager.get_history(session_id)
        if not history:
            return "新对话"
        if self.llm_provider:
            try:
                msgs = [
                    {"role": "system", "content": "为以下对话生成一个简短标题（10字以内），只输出标题。"},
                    {"role": "user", "content": "\n".join([m.get("content", "")[:100] for m in history[-4:]])}
                ]
                title = await self.llm_provider.chat(msgs)
                return title.strip()[:20] if title else "未命名"
            except Exception as e:
                logger.warning(f"标题生成失败: {e}")
        return "未命名"

    async def export_session(self, session_id: str, format: str = "markdown") -> str:
        history = self.session_manager.get_history(session_id)
        if format == "markdown":
            lines = ["# SEAI 对话记录\n"]
            for msg in history:
                role = "**用户**" if msg["role"] == "user" else "**SEAI**"
                lines.append(f"{role}:\n{msg['content']}\n")
            return "\n".join(lines)
        return json.dumps(history, indent=2, ensure_ascii=False)

    def load_history(self, session_id: str) -> List[Dict]:
        if not session_id:
            return []
        try:
            return self.session_manager.get_history(session_id)
        except Exception:
            return []

    def save_message(self, session_id: str, role: str, content: str, token_count: int = 0):
        if not session_id or not content:
            return
        try:
            self.session_manager.add_message(role, content)
            if token_count > 0:
                try:
                    from .database import async_db_manager
                    awaitable = async_db_manager.add_message(session_id, role, content, token_count)
                    import asyncio
                    try:
                        asyncio.create_task(awaitable)
                    except RuntimeError:
                        pass
                except Exception as e:
                    logger.debug(f"数据库消息 token 记录失败（非关键）: {e}")
            self._save_context_async(session_id)
        except Exception as e:
            logger.warning(f"保存消息失败: {e}")

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
        except Exception as e:
            logger.debug(f"上下文保存失败（非关键）: {e}")

    def get_stats(self) -> dict:
        sessions = self.list_sessions()
        total_messages = 0
        for s in sessions:
            history = self.load_history(s.get("id", ""))
            total_messages += len(history)
        return {
            "session_count": len(sessions),
            "total_messages": total_messages,
            "current_session": self.get_current_session_id(),
        }