"""
数据仓库层单元测试
"""
import pytest
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from seai.core.repository.config_repo import ConfigRepository
from seai.core.repository.session_repo import SessionRepository
from seai.core.repository.memory_repo import MemoryRepository


class TestConfigRepository:
    @pytest.fixture
    def config_path(self, temp_dir):
        return temp_dir / "test_config.json"

    @pytest.fixture
    def repo(self, config_path):
        return ConfigRepository(config_path)

    def test_save_and_load(self, repo):
        config = {"api_key": "test-key", "model": "gpt-4"}
        assert repo.save(config) is True
        loaded = repo.load()
        assert loaded["model"] == "gpt-4"

    def test_api_key_encrypted_on_disk(self, repo, config_path):
        config = {"api_key": "secret-123", "model": "gpt-4"}
        repo.save(config)
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        assert raw["api_key"].startswith("enc:")
        assert raw["model"] == "gpt-4"

    def test_api_key_decrypted_on_load(self, repo):
        config = {"api_key": "secret-456"}
        repo.save(config)
        loaded = repo.load()
        assert loaded["api_key"] == "secret-456"

    def test_get_and_set(self, repo):
        repo.set("theme", "dark")
        assert repo.get("theme") == "dark"
        assert repo.get("nonexistent", "default") == "default"

    def test_update(self, repo):
        repo.save({"a": 1, "b": 2})
        repo.update({"b": 3, "c": 4})
        loaded = repo.load()
        assert loaded["a"] == 1
        assert loaded["b"] == 3
        assert loaded["c"] == 4


class TestSessionRepository:
    @pytest.fixture
    def repo(self, temp_dir):
        return SessionRepository(temp_dir)

    def test_save_and_get_session(self, repo):
        data = {"title": "测试会话", "messages": []}
        assert repo.save_session("sess-1", data) is True
        loaded = repo.get_session("sess-1")
        assert loaded["title"] == "测试会话"

    def test_list_sessions(self, repo):
        repo.save_session("sess-a", {"title": "A", "messages": []})
        repo.save_session("sess-b", {"title": "B", "messages": []})
        sessions = repo.list_sessions()
        assert len(sessions) == 2

    def test_delete_session(self, repo):
        repo.save_session("sess-x", {"title": "X", "messages": []})
        assert repo.delete_session("sess-x") is True
        assert repo.get_session("sess-x") is None

    def test_add_message(self, repo):
        repo.save_session("sess-1", {"title": "Test", "messages": []})
        repo.add_message("sess-1", "user", "Hello")
        history = repo.get_history("sess-1")
        assert len(history) == 1
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"

    def test_rename_session(self, repo):
        repo.save_session("sess-1", {"title": "Old", "messages": []})
        repo.rename_session("sess-1", "New Name")
        loaded = repo.get_session("sess-1")
        assert loaded["title"] == "New Name"


class TestMemoryRepository:
    @pytest.fixture
    def repo(self, temp_dir):
        return MemoryRepository(temp_dir)

    def test_add_and_get_memories(self, repo):
        import time
        entry = {"id": "mem-1", "text": "test memory", "last_access": time.time()}
        repo.add_long_term_memory(entry)
        memories = repo.get_long_term_memories()
        assert len(memories) >= 1

    def test_user_profile(self, repo):
        repo.update_user_profile("# User Profile\nTest content")
        content = repo.get_user_profile()
        assert "Test content" in content

    def test_global_knowledge(self, repo):
        repo.update_global_knowledge("# Knowledge\nTest knowledge")
        content = repo.get_global_knowledge()
        assert "Test knowledge" in content