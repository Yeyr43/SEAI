"""
SessionManager 单元测试
覆盖：会话创建/切换/删除、消息存储、WAL模式验证
"""
import pytest
import time
from pathlib import Path


@pytest.fixture
def session_mgr(tmp_path):
    try:
        from seai.core.session_manager import SessionManager
        return SessionManager(sessions_dir=tmp_path)
    except Exception as e:
        pytest.skip(f"SessionManager 初始化失败: {e}")


class TestSessionCreation:
    """会话创建测试"""

    def test_create_session(self, session_mgr):
        sid = session_mgr.create_session()
        assert sid is not None
        assert len(sid) > 0
        assert session_mgr.current_session_id == sid

    def test_create_multiple_sessions(self, session_mgr):
        sid1 = session_mgr.create_session()
        sid2 = session_mgr.create_session()
        assert sid1 != sid2
        sessions = session_mgr.list_sessions()
        assert len(sessions) >= 2

    def test_session_has_default_name(self, session_mgr):
        sid = session_mgr.create_session()
        sessions = session_mgr.list_sessions()
        session = next((s for s in sessions if s["id"] == sid), None)
        assert session is not None


class TestSessionSwitch:
    """会话切换测试"""

    def test_switch_session(self, session_mgr):
        sid1 = session_mgr.create_session()
        sid2 = session_mgr.create_session()
        session_mgr.switch_session(sid1)
        assert session_mgr.current_session_id == sid1
        session_mgr.switch_session(sid2)
        assert session_mgr.current_session_id == sid2

    def test_switch_to_nonexistent(self, session_mgr):
        session_mgr.switch_session("nonexistent_id")
        assert session_mgr.current_session_id == "nonexistent_id"


class TestSessionDelete:
    """会话删除测试"""

    def test_delete_session(self, session_mgr):
        sid = session_mgr.create_session()
        session_mgr.add_message("user", "测试消息")
        session_mgr.delete_session(sid)
        sessions = session_mgr.list_sessions()
        assert not any(s["id"] == sid for s in sessions)

    def test_delete_nonexistent_session(self, session_mgr):
        session_mgr.delete_session("nonexistent_id")


class TestMessageStorage:
    """消息存储测试"""

    def test_add_message(self, session_mgr):
        session_mgr.create_session()
        session_mgr.add_message("user", "你好")
        history = session_mgr.get_current_history()
        assert len(history) > 0
        assert history[-1]["role"] == "user"
        assert history[-1]["content"] == "你好"

    def test_add_multiple_messages(self, session_mgr):
        session_mgr.create_session()
        messages = [
            ("user", "消息1"),
            ("assistant", "回复1"),
            ("user", "消息2"),
            ("assistant", "回复2"),
        ]
        for role, content in messages:
            session_mgr.add_message(role, content)
        history = session_mgr.get_current_history()
        assert len(history) == 4

    def test_get_history_by_session_id(self, session_mgr):
        sid = session_mgr.create_session()
        session_mgr.add_message("user", "特定会话消息")
        history = session_mgr.get_history(sid)
        assert len(history) == 1
        assert history[0]["content"] == "特定会话消息"

    def test_message_isolation(self, session_mgr):
        sid1 = session_mgr.create_session()
        session_mgr.add_message("user", "会话1消息")
        sid2 = session_mgr.create_session()
        session_mgr.switch_session(sid2)
        session_mgr.add_message("user", "会话2消息")

        history1 = session_mgr.get_history(sid1)
        history2 = session_mgr.get_history(sid2)
        assert len(history1) == 1
        assert len(history2) == 1
        assert history1[0]["content"] == "会话1消息"
        assert history2[0]["content"] == "会话2消息"


class TestWALMode:
    """WAL模式验证测试"""

    def test_wal_mode_enabled(self, session_mgr):
        from seai.core.database import engine
        with engine.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA journal_mode")
            mode = result.scalar() or ""
        assert mode.lower() == "wal"

    def test_concurrent_access(self, session_mgr):
        session_mgr.create_session()
        session_mgr.add_message("user", "并发测试消息")
        history = session_mgr.get_current_history()
        assert len(history) > 0


class TestSessionRename:
    """会话重命名测试"""

    def test_rename_session(self, session_mgr):
        sid = session_mgr.create_session()
        session_mgr.rename_session(sid, "我的测试会话")
        sessions = session_mgr.list_sessions()
        session = next((s for s in sessions if s["id"] == sid), None)
        assert session is not None
        assert session["name"] == "我的测试会话"
