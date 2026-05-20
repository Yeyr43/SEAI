"""
会话数据仓库
封装会话相关的数据持久化操作
"""
from pathlib import Path
from typing import List, Dict, Optional
from .base import BaseRepository


class SessionRepository(BaseRepository[Dict]):
    def __init__(self, data_dir: Path):
        super().__init__()
        self.data_dir = data_dir
        self.sessions_dir = data_dir / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def list_sessions(self) -> List[Dict]:
        sessions = []
        if not self.sessions_dir.exists():
            return sessions
        for f in sorted(self.sessions_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            data = self._read_json(f)
            if data:
                sessions.append({
                    "id": f.stem,
                    "title": data.get("title", "未命名"),
                    "message_count": len(data.get("messages", [])),
                    "updated_at": data.get("updated_at", ""),
                })
        return sessions

    def get_session(self, session_id: str) -> Optional[Dict]:
        path = self.sessions_dir / f"{session_id}.json"
        if not path.exists():
            return None
        return self._read_json(path)

    def save_session(self, session_id: str, data: Dict) -> bool:
        path = self.sessions_dir / f"{session_id}.json"
        return self._write_json(path, data)

    def delete_session(self, session_id: str) -> bool:
        path = self.sessions_dir / f"{session_id}.json"
        try:
            if path.exists():
                path.unlink()
            return True
        except Exception:
            return False

    def get_history(self, session_id: str) -> List[Dict]:
        data = self.get_session(session_id)
        if data:
            return data.get("messages", [])
        return []

    def add_message(self, session_id: str, role: str, content: str) -> bool:
        data = self.get_session(session_id) or {"title": "未命名", "messages": [], "updated_at": ""}
        from datetime import datetime
        data["messages"].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        data["updated_at"] = datetime.now().isoformat()
        return self.save_session(session_id, data)

    def rename_session(self, session_id: str, name: str) -> bool:
        data = self.get_session(session_id)
        if data:
            data["title"] = name
            return self.save_session(session_id, data)
        return False