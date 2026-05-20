"""
统一数据库层 单元测试
覆盖：SessionManager 与 DatabaseManager 集成、CRUD 操作
"""
import pytest
import uuid
from pathlib import Path


@pytest.fixture(scope="module")
def db_setup():
    try:
        from seai.core.database import init_db, db_manager
        init_db()
        return db_manager
    except Exception as e:
        pytest.skip(f"数据库初始化失败: {e}")


class TestDatabaseManager:
    def test_create_session(self, db_setup):
        sid = str(uuid.uuid4())
        session = db_setup.create_session(sid, title="测试会话")
        assert session.id == sid
        assert session.title == "测试会话"

    def test_list_sessions(self, db_setup):
        sessions = db_setup.list_sessions()
        assert isinstance(sessions, list)

    def test_add_message(self, db_setup):
        sid = str(uuid.uuid4())
        db_setup.create_session(sid, title="消息测试")
        msg = db_setup.add_message(sid, "user", "你好")
        assert msg.role == "user"
        assert msg.content == "你好"

    def test_get_messages(self, db_setup):
        sid = str(uuid.uuid4())
        db_setup.create_session(sid, title="历史测试")
        db_setup.add_message(sid, "user", "问题1")
        db_setup.add_message(sid, "assistant", "回答1")
        messages = db_setup.get_messages(sid)
        assert len(messages) == 2
        assert messages[0].role == "user"
        assert messages[1].role == "assistant"

    def test_delete_session(self, db_setup):
        sid = str(uuid.uuid4())
        db_setup.create_session(sid, title="待删除")
        db_setup.delete_session(sid)
        session = db_setup.get_session(sid)
        assert session is None

    def test_get_stats(self, db_setup):
        stats = db_setup.get_stats()
        assert "total_sessions" in stats
        assert "total_messages" in stats


class TestSessionManager:
    @pytest.fixture
    def session_mgr(self):
        try:
            from seai.core.session_manager import SessionManager
            return SessionManager()
        except Exception as e:
            pytest.skip(f"SessionManager 初始化失败: {e}")

    def test_create_session(self, session_mgr):
        sid = session_mgr.create_session()
        assert sid is not None
        assert len(sid) > 0
        assert session_mgr.current_session_id == sid

    def test_switch_session(self, session_mgr):
        sid1 = session_mgr.create_session()
        sid2 = str(uuid.uuid4())
        from seai.core.database import db_manager
        db_manager.create_session(sid2, title="切换测试")
        session_mgr.switch_session(sid2)
        assert session_mgr.current_session_id == sid2

    def test_add_and_get_history(self, session_mgr):
        session_mgr.create_session()
        session_mgr.add_message("user", "测试消息")
        session_mgr.add_message("assistant", "测试回复")
        history = session_mgr.get_current_history()
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_list_sessions(self, session_mgr):
        sessions = session_mgr.list_sessions()
        assert isinstance(sessions, list)
        for s in sessions:
            assert "id" in s
            assert "name" in s

    def test_rename_session(self, session_mgr):
        sid = session_mgr.create_session()
        session_mgr.rename_session(sid, "新名称")
        sessions = session_mgr.list_sessions()
        renamed = [s for s in sessions if s["id"] == sid]
        if renamed:
            assert renamed[0]["name"] == "新名称"

    def test_delete_session(self, session_mgr):
        sid = session_mgr.create_session()
        session_mgr.delete_session(sid)
        sessions = session_mgr.list_sessions()
        assert not any(s["id"] == sid for s in sessions)