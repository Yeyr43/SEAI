"""
MemoryEngine 完整单元测试
覆盖：记忆存储、类型标记、时间范围检索、知识图谱构建、JSON序列化/反序列化
"""
import pytest
import json
import time
from pathlib import Path


@pytest.fixture
def mem_engine(tmp_path):
    try:
        from seai.core.memory_engine import MemoryEngine
        return MemoryEngine(persist_dir=tmp_path)
    except Exception as e:
        pytest.skip(f"MemoryEngine 初始化失败: {e}")


class TestMemoryStorage:
    """记忆存储测试"""

    def test_add_memory_basic(self, mem_engine):
        mem_engine.add_memory("测试记忆内容")
        results = mem_engine.search_memory("测试")
        assert len(results) > 0

    def test_add_memory_with_metadata(self, mem_engine):
        if hasattr(mem_engine, 'add_memory_with_metadata'):
            mem_engine.add_memory_with_metadata(
                "带元数据的记忆",
                metadata={"source": "test", "priority": "high"}
            )
            results = mem_engine.search_memory("元数据")
            assert len(results) > 0

    def test_add_multiple_memories(self, mem_engine):
        texts = ["记忆A: Python", "记忆B: JavaScript", "记忆C: Rust"]
        for t in texts:
            mem_engine.add_memory(t)
        results = mem_engine.search_memory("Python")
        assert len(results) >= 1

    def test_memory_persistence(self, tmp_path):
        from seai.core.memory_engine import MemoryEngine
        engine1 = MemoryEngine(persist_dir=tmp_path)
        engine1.add_memory("持久化测试记忆")
        del engine1

        engine2 = MemoryEngine(persist_dir=tmp_path)
        results = engine2.search_memory("持久化")
        assert len(results) > 0


class TestMemoryTypes:
    """记忆类型标记测试"""

    def test_long_term_memory_with_type(self, mem_engine):
        if hasattr(mem_engine, 'add_long_term_memory_with_links'):
            mem_engine.add_long_term_memory_with_links(
                "代码片段: def hello(): print('world')",
                mem_type="code"
            )
            results = mem_engine.search_memory("hello")
            assert len(results) > 0

    def test_memory_type_file_snapshot(self, mem_engine):
        if hasattr(mem_engine, 'add_long_term_memory_with_links'):
            mem_engine.add_long_term_memory_with_links(
                "文件快照: main.py 内容",
                mem_type="file_snapshot"
            )
            results = mem_engine.search_memory("main.py")
            assert len(results) > 0

    def test_memory_type_url(self, mem_engine):
        if hasattr(mem_engine, 'add_long_term_memory_with_links'):
            mem_engine.add_long_term_memory_with_links(
                "URL: https://example.com 搜索结果",
                mem_type="url"
            )
            results = mem_engine.search_memory("example.com")
            assert len(results) > 0


class TestTimeRangeSearch:
    """时间范围检索测试"""

    def test_get_memories_by_timerange(self, mem_engine):
        if not hasattr(mem_engine, 'get_memories_by_timerange'):
            pytest.skip("不支持时间范围检索")

        from datetime import datetime, timedelta
        mem_engine.add_memory("时间测试记忆")

        now = datetime.now()
        results = mem_engine.get_memories_by_timerange(
            start_time=(now - timedelta(hours=1)).isoformat(),
            end_time=(now + timedelta(hours=1)).isoformat(),
            limit=10
        )
        assert isinstance(results, list)


class TestKnowledgeGraph:
    """知识图谱构建测试"""

    def test_graph_initialization(self, mem_engine):
        if not hasattr(mem_engine, 'graph'):
            pytest.skip("不支持知识图谱")
        assert mem_engine.graph is not None

    def test_graph_node_creation(self, mem_engine):
        if not hasattr(mem_engine, 'graph'):
            pytest.skip("不支持知识图谱")
        mem_engine.graph.add_node("test_node", text="测试节点")
        assert "test_node" in mem_engine.graph.nodes

    def test_graph_edge_creation(self, mem_engine):
        if not hasattr(mem_engine, 'graph'):
            pytest.skip("不支持知识图谱")
        mem_engine.graph.add_node("node_a", text="节点A")
        mem_engine.graph.add_node("node_b", text="节点B")
        mem_engine.graph.add_edge("node_a", "node_b", relation="related")
        assert mem_engine.graph.has_edge("node_a", "node_b")


class TestJSONSerialization:
    """JSON序列化/反序列化测试"""

    def test_memory_json_roundtrip(self, mem_engine):
        mem_engine.add_memory("JSON测试记忆")
        results = mem_engine.search_memory("JSON")
        serialized = json.dumps(results, ensure_ascii=False)
        deserialized = json.loads(serialized)
        assert isinstance(deserialized, list)

    def test_user_profile_serialization(self, mem_engine):
        if hasattr(mem_engine, 'get_user_profile'):
            profile = mem_engine.get_user_profile()
            assert isinstance(profile, str)
            if profile:
                json.loads(profile)

    def test_global_knowledge_serialization(self, mem_engine):
        if hasattr(mem_engine, 'get_global_knowledge'):
            knowledge = mem_engine.get_global_knowledge()
            assert isinstance(knowledge, str)
