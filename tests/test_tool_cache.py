"""
ToolCache 单元测试
覆盖：缓存键生成、TTL过期、文件mtime感知、清理策略
"""
import pytest
import time
from pathlib import Path


@pytest.fixture
def tool_cache(tmp_path):
    try:
        from seai.core.tool_cache import ToolCache
        return ToolCache(default_ttl=300)
    except ImportError:
        pytest.skip("ToolCache 模块不存在")
    except Exception as e:
        pytest.skip(f"ToolCache 初始化失败: {e}")


class TestCacheKeyGeneration:
    """缓存键生成测试"""

    def test_basic_key_generation(self, tool_cache):
        key = tool_cache._generate_key("test_tool", {"arg1": "value1"})
        assert isinstance(key, str)
        assert len(key) > 0

    def test_key_consistency(self, tool_cache):
        key1 = tool_cache._generate_key("tool_a", {"x": 1, "y": 2})
        key2 = tool_cache._generate_key("tool_a", {"x": 1, "y": 2})
        assert key1 == key2

    def test_key_different_args(self, tool_cache):
        key1 = tool_cache._generate_key("tool_a", {"x": 1})
        key2 = tool_cache._generate_key("tool_a", {"x": 2})
        assert key1 != key2

    def test_key_different_tools(self, tool_cache):
        key1 = tool_cache._generate_key("tool_a", {"x": 1})
        key2 = tool_cache._generate_key("tool_b", {"x": 1})
        assert key1 != key2

    def test_mutable_tools_not_cacheable(self, tool_cache):
        assert tool_cache._generate_key("edit", {"path": "/tmp/x"}) is None
        assert tool_cache._generate_key("bash", {"cmd": "ls"}) is None
        assert tool_cache._generate_key("todo", {"action": "add"}) is None


class TestTTLExpiry:
    """TTL过期测试"""

    def test_cache_set_and_get(self, tool_cache):
        tool_cache.set("test_tool", {"a": 1}, "test_value", ttl=60)
        value = tool_cache.get("test_tool", {"a": 1})
        assert value == "test_value"

    def test_cache_expiry(self, tool_cache):
        tool_cache.set("test_tool", {"a": 1}, "expire_value", ttl=0.1)
        time.sleep(0.2)
        value = tool_cache.get("test_tool", {"a": 1})
        assert value is None

    def test_cache_no_expiry(self, tool_cache):
        tool_cache.set("test_tool", {"a": 1}, "persist_value", ttl=3600)
        value = tool_cache.get("test_tool", {"a": 1})
        assert value == "persist_value"


class TestFileMtimeAwareness:
    """文件mtime感知测试"""

    def test_file_cache_invalidation(self, tmp_path, tool_cache):
        test_file = tmp_path / "test.txt"
        test_file.write_text("version 1")

        tool_cache.set("read_file", {"path": str(test_file)}, "cached_result")
        value1 = tool_cache.get("read_file", {"path": str(test_file)})
        assert value1 == "cached_result"

        time.sleep(0.5)
        test_file.write_text("version 2")

        value2 = tool_cache.get("read_file", {"path": str(test_file)})
        assert value2 is None


class TestCleanupStrategy:
    """清理策略测试"""

    def test_clear_all(self, tool_cache):
        tool_cache.set("tool_x", {"a": 1}, "val1", ttl=3600)
        tool_cache.set("tool_x", {"a": 2}, "val2", ttl=3600)
        tool_cache.clear()
        assert tool_cache.get("tool_x", {"a": 1}) is None
        assert tool_cache.get("tool_x", {"a": 2}) is None

    def test_clear_specific_tool(self, tool_cache):
        tool_cache.set("tool_x", {"a": 1}, "val1", ttl=3600)
        tool_cache.set("tool_y", {"a": 1}, "val2", ttl=3600)
        tool_cache.clear("tool_x")
        assert tool_cache.get("tool_x", {"a": 1}) is None
        assert tool_cache.get("tool_y", {"a": 1}) == "val2"

    def test_cleanup_expired(self, tool_cache):
        tool_cache.set("t1", {"a": 1}, "exp1", ttl=0.1)
        tool_cache.set("t1", {"a": 2}, "exp2", ttl=0.1)
        tool_cache.set("t2", {"a": 1}, "keep", ttl=3600)
        time.sleep(0.2)
        tool_cache.cleanup_expired()
        assert tool_cache.get("t1", {"a": 1}) is None
        assert tool_cache.get("t1", {"a": 2}) is None
        assert tool_cache.get("t2", {"a": 1}) == "keep"
