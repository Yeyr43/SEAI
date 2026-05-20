# ══════════════════════════════════════════════════
# core/session_manager.py - 会话管理器（时间戳ID + 独立文件存储 + 关键词命名）
# ══════════════════════════════════════════════════
import os
import re
import time
import gzip
import json
import tempfile
import threading
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime, timezone

from loguru import logger

KEYWORD_PATTERNS = [
    (r"(代码|编程|bug|debug|函数|python|java|go|rust|算法|重构|优化|修复)", "编程"),
    (r"(搜索|查询|查找|检索|search|find)", "搜索"),
    (r"(写|创作|文章|故事|诗|文案|write|create|draw)", "创作"),
    (r"(文件|读取|写入|删除|目录|路径|file|read|write)", "文件操作"),
    (r"(配置|设置|安装|部署|config|setup|install)", "配置"),
    (r"(测试|test|验证|检查|verify|check)", "测试"),
    (r"(学习|教程|解释|说明|什么是|如何|learn|tutorial)", "学习"),
    (r"(聊天|对话|闲聊|hello|hi|你好)", "闲聊"),
    (r"(待办|提醒|日程|计划|安排|todo|schedule)", "计划"),
    (r"(技能|skill|插件|plugin|扩展)", "技能"),
    (r"(记忆|memory|回忆|历史|记录)", "记忆"),
    (r"(进化|反思|优化|改进|evolve|reflect)", "进化"),
]


class SessionManager:

    def __init__(self, sessions_dir: Path = None):
        self.current_session_id = ""
        self._sessions_dir: Optional[Path] = None
        self._context_dir: Optional[Path] = None
        self._first_message_recorded: Dict[str, bool] = {}
        self._session_name_cache: Dict[str, str] = {}
        self._write_locks: Dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()

    def set_sessions_dir(self, sessions_dir: Path):
        self._sessions_dir = Path(sessions_dir)
        self._sessions_dir.mkdir(parents=True, exist_ok=True)

    def set_context_dir(self, context_dir: Path):
        self._context_dir = Path(context_dir)
        self._context_dir.mkdir(parents=True, exist_ok=True)

    def _generate_session_id(self) -> str:
        return datetime.now().strftime("%Y%m%d%H%M%S%f")

    def _get_session_file_path(self, session_id: str) -> Optional[Path]:
        if not self._sessions_dir:
            return None
        return self._sessions_dir / f"{session_id}.json"

    def _extract_keywords(self, text: str) -> str:
        if not text:
            return "新对话"
        for pattern, category in KEYWORD_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return category
        cleaned = re.sub(r'[^\w\u4e00-\u9fff]', '', text)
        if len(cleaned) <= 10:
            return cleaned if cleaned else "新对话"
        return cleaned[:10]

    def create_session(self, first_message: str = "") -> str:
        self.current_session_id = self._generate_session_id()

        if first_message:
            keyword = self._extract_keywords(first_message)
            name = f"{keyword}-{self.current_session_id[-6:]}"
        else:
            name = f"新对话-{self.current_session_id[-6:]}"

        self._session_name_cache[self.current_session_id] = name

        session_data = {
            "session_id": self.current_session_id,
            "title": name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "message_count": 0,
            "messages": [],
        }
        self._save_session_file(self.current_session_id, session_data)

        try:
            from .database import db_manager
            db_manager.create_session(self.current_session_id, title=name)
        except Exception as e:
            logger.debug(f"数据库同步失败（非关键）: {e}")

        logger.info(f"会话已创建: {self.current_session_id} ({name})")
        return self.current_session_id

    def switch_session(self, sid: str):
        self.current_session_id = sid

    def rename_session(self, sid: str, name: str):
        self._session_name_cache[sid] = name
        session_data = self._load_session_file(sid)
        if session_data:
            session_data["title"] = name
            session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_session_file(sid, session_data)
        try:
            from .database import db_manager
            with db_manager._get_db() as db:
                from .database import SessionModel
                s = db.query(SessionModel).filter(SessionModel.id == sid).first()
                if s:
                    s.title = name
                    s.updated_at = datetime.now(timezone.utc)
                    db.commit()
        except Exception as e:
            logger.debug(f"数据库重命名同步失败: {e}")

    def auto_name_session(self, sid: str, first_message: str):
        if sid in self._session_name_cache and self._session_name_cache[sid] != f"新对话-{sid[-6:]}":
            return
        keyword = self._extract_keywords(first_message)
        name = f"{keyword}-{sid[-6:]}"
        self.rename_session(sid, name)

    def delete_session(self, sid: str):
        file_path = self._get_session_file_path(sid)
        if file_path and file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                logger.warning(f"删除会话文件失败 [{sid}]: {e}")

        self._delete_context_file(sid)
        self._session_name_cache.pop(sid, None)

        try:
            from .database import db_manager
            db_manager.delete_session(sid)
        except Exception as e:
            logger.debug(f"数据库删除会话失败（非关键）: {e}")

    def list_sessions(self) -> List[Dict]:
        sessions = []
        if self._sessions_dir and self._sessions_dir.exists():
            for f in sorted(self._sessions_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                session_data = self._load_session_file(f.stem)
                if session_data:
                    sessions.append({
                        "id": session_data.get("session_id", f.stem),
                        "name": session_data.get("title", "未命名"),
                        "created_at": self._parse_iso(session_data.get("created_at", "")),
                        "updated_at": self._parse_iso(session_data.get("updated_at", "")),
                        "message_count": session_data.get("message_count", 0),
                    })

        if not sessions:
            try:
                from .database import db_manager
                db_sessions = db_manager.list_sessions()
                sessions = [
                    {
                        "id": s.id,
                        "name": s.title or "未命名",
                        "created_at": s.created_at.timestamp() if s.created_at else time.time(),
                        "updated_at": s.updated_at.timestamp() if s.updated_at else time.time(),
                    }
                    for s in db_sessions
                ]
            except Exception as e:
                logger.debug(f"数据库会话列表加载失败（非关键）: {e}")

        return sessions

    def _parse_iso(self, iso_str: str) -> float:
        try:
            return datetime.fromisoformat(iso_str).timestamp()
        except Exception:
            return time.time()

    @staticmethod
    def _sanitize_history(messages: List[Dict]) -> List[Dict]:
        """清理历史消息中的孤立 tool 消息（缺少前置 tool_calls 的消息）"""
        if not messages:
            return messages
        cleaned = []
        for msg in messages:
            if msg.get("role") == "tool":
                # tool 消息必须有前置 assistant 消息包含 tool_calls
                if not cleaned or cleaned[-1].get("role") != "assistant" or "tool_calls" not in cleaned[-1]:
                    continue
            cleaned.append(msg)
        return cleaned

    def get_current_history(self) -> List[Dict]:
        if not self.current_session_id:
            self.create_session()
        return self._sanitize_history(self.get_history(self.current_session_id))

    def get_history(self, sid: str) -> List[Dict]:
        session_data = self._load_session_file(sid)
        if session_data:
            return self._sanitize_history(session_data.get("messages", []))

        try:
            from .database import db_manager
            messages = db_manager.get_messages(sid)
            result = []
            for m in messages:
                msg = {"role": m.role, "content": m.content}
                if hasattr(m, "tool_calls") and m.tool_calls:
                    msg["tool_calls"] = m.tool_calls
                if hasattr(m, "tool_call_id") and m.tool_call_id:
                    msg["tool_call_id"] = m.tool_call_id
                result.append(msg)
            return result
        except Exception:
            return []

    def add_message(self, role: str, content: str, **extra_fields):
        if not self.current_session_id:
            self.create_session()

        session_data = self._load_session_file(self.current_session_id)
        if session_data is None:
            session_data = {
                "session_id": self.current_session_id,
                "title": self._session_name_cache.get(self.current_session_id, "新对话"),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "message_count": 0,
                "messages": [],
            }

        msg = {"role": role, "content": content}
        msg.update(extra_fields)
        session_data["messages"].append(msg)
        session_data["message_count"] = len(session_data["messages"])
        session_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_session_file(self.current_session_id, session_data)

        if role == "user" and session_data["message_count"] == 1:
            self.auto_name_session(self.current_session_id, content)

        try:
            from .database import db_manager
            db_manager.add_message(self.current_session_id, role, content)
        except Exception as e:
            logger.debug(f"数据库添加消息失败（非关键）: {e}")

    def _load_session_file(self, session_id: str) -> Optional[Dict]:
        if not self._sessions_dir:
            return None
        file_path = self._get_session_file_path(session_id)
        if not file_path or not file_path.exists():
            return None
        try:
            return json.loads(file_path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"加载会话文件失败 [{session_id}]: {e}")
            return None

    def _get_lock(self, session_id: str) -> threading.Lock:
        with self._locks_lock:
            if session_id not in self._write_locks:
                self._write_locks[session_id] = threading.Lock()
            return self._write_locks[session_id]

    def _save_session_file(self, session_id: str, data: Dict) -> bool:
        if not self._sessions_dir:
            return False
        file_path = self._get_session_file_path(session_id)
        if not file_path:
            return False
        lock = self._get_lock(session_id)
        with lock:
            try:
                file_path.parent.mkdir(parents=True, exist_ok=True)
                raw = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
                fd, tmp = tempfile.mkstemp(
                    suffix=".json", prefix=f".{session_id}_", dir=str(file_path.parent)
                )
                try:
                    os.write(fd, raw)
                finally:
                    os.close(fd)
                os.replace(tmp, file_path)  # Windows 上原子重命名
                return True
            except Exception as e:
                logger.error(f"保存会话文件失败 [{session_id}]: {e}")
                return False

    def _get_context_file_path(self, session_id: str) -> Optional[Path]:
        if not self._context_dir:
            return None
        return self._context_dir / f"ctx_{session_id}.json.gz"

    def save_context_to_file(self, session_id: str = None):
        sid = session_id or self.current_session_id
        if not sid or not self._context_dir:
            return

        file_path = self._get_context_file_path(sid)
        if not file_path:
            return

        history = self.get_history(sid)
        if not history:
            return

        session_data = self._load_session_file(sid)
        session_info = {}
        if session_data:
            session_info = {
                "title": session_data.get("title", ""),
                "message_count": session_data.get("message_count", 0),
                "created_at": session_data.get("created_at"),
                "updated_at": session_data.get("updated_at"),
            }

        context_data = {
            "session_id": sid,
            "session_info": session_info,
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "message_count": len(history),
            "messages": [
                {
                    "role": msg["role"],
                    "content": self._compress_content(msg["content"])
                }
                for msg in history
            ]
        }

        compressed = gzip.compress(
            json.dumps(context_data, ensure_ascii=False).encode("utf-8"),
            compresslevel=6
        )
        file_path.write_bytes(compressed)

    def _compress_content(self, content: str) -> str:
        if len(content) <= 500:
            return content
        head = content[:200]
        tail = content[-200:]
        return f"{head}\n...[压缩省略 {len(content) - 400} 字符]...\n{tail}"

    def load_context_from_file(self, session_id: str) -> Optional[Dict]:
        if not self._context_dir:
            return None

        file_path = self._get_context_file_path(session_id)
        if not file_path or not file_path.exists():
            return None

        try:
            compressed = file_path.read_bytes()
            decompressed = gzip.decompress(compressed)
            return json.loads(decompressed.decode("utf-8"))
        except Exception:
            return None

    def _delete_context_file(self, session_id: str):
        if not self._context_dir:
            return

        file_path = self._get_context_file_path(session_id)
        if file_path and file_path.exists():
            try:
                file_path.unlink()
            except Exception as e:
                logger.warning(f"删除上下文文件失败 [{session_id}]: {e}")

    def cleanup_orphan_context_files(self):
        if not self._context_dir or not self._context_dir.exists():
            return

        active_ids = {s["id"] for s in self.list_sessions()}
        for ctx_file in self._context_dir.glob("ctx_*.json.gz"):
            sid = ctx_file.stem.replace("ctx_", "").replace(".json", "")
            if sid not in active_ids:
                try:
                    ctx_file.unlink()
                except Exception as e:
                    logger.warning(f"清理孤儿上下文文件失败 [{sid}]: {e}")

    def get_session_name(self, session_id: str) -> str:
        if session_id in self._session_name_cache:
            return self._session_name_cache[session_id]
        session_data = self._load_session_file(session_id)
        if session_data:
            name = session_data.get("title", "未命名")
            self._session_name_cache[session_id] = name
            return name
        return "未命名"