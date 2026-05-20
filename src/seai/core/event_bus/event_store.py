"""事件持久化存储 — SQLite 消息回溯"""
import json
import threading
from typing import List, Optional
from pathlib import Path
from .message import Message


class EventStore:
    """事件持久化存储 — 基于 SQLite 实现消息回溯"""

    def __init__(self, db_path: str = None):
        import sqlite3
        self._db_path = db_path or "data/event_store.db"
        self._local: Optional[threading.local] = None

    def _get_conn(self):
        import sqlite3
        ident = threading.get_ident()
        if self._local is None:
            self._local = threading.local()
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(self._db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                "CREATE TABLE IF NOT EXISTS messages ("
                "  id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "  msg_id TEXT UNIQUE,"
                "  task_id TEXT,"
                "  sender TEXT,"
                "  target TEXT,"
                "  intent TEXT,"
                "  payload TEXT,"
                "  timestamp REAL"
                ")"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_task_id ON messages(task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON messages(timestamp)")
            conn.commit()
            self._local.conn = conn
        return conn

    def store(self, msg: Message):
        conn = self._get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO messages (msg_id, task_id, sender, target, intent, payload, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (msg.msg_id, msg.task_id, msg.sender, msg.target, msg.intent,
             json.dumps(msg.payload, ensure_ascii=False) if msg.payload is not None else None,
             msg.timestamp)
        )
        conn.commit()

    def query(self, task_id: str = None, limit: int = 100) -> List[Message]:
        conn = self._get_conn()
        if task_id:
            rows = conn.execute(
                "SELECT * FROM messages WHERE task_id = ? ORDER BY timestamp DESC LIMIT ?",
                (task_id, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY timestamp DESC LIMIT ?",
                (limit,)
            ).fetchall()
        results = []
        for row in rows:
            payload = json.loads(row[6]) if row[6] else None
            results.append(Message(
                msg_id=row[1], task_id=row[2], sender=row[3], target=row[4],
                intent=row[5], payload=payload, timestamp=row[7]
            ))
        return results

    def close(self):
        if self._local is not None and hasattr(self._local, 'conn'):
            self._local.conn.close()
            self._local.conn = None
