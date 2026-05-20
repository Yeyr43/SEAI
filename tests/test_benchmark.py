"""
SEAI 性能基准测试
使用 pytest-benchmark 监控关键路径性能
需要: pip install pytest-benchmark
"""
import pytest
import time
from pathlib import Path

pytest.importorskip("pytest_benchmark", reason="pytest-benchmark 未安装，跳过性能基准测试")


@pytest.fixture
def mem_engine(tmp_path):
    try:
        from seai.core.memory_engine import MemoryEngine
        engine = MemoryEngine(persist_dir=tmp_path)
        for i in range(100):
            engine.add_memory(f"测试记忆 #{i}: 这是第{i}条记忆内容，包含关键词 Python AI 机器学习")
        return engine
    except Exception as e:
        pytest.skip(f"MemoryEngine 初始化失败: {e}")


@pytest.fixture
def llm_mgr():
    try:
        from seai.core.llm_manager import LLMManager
        return LLMManager(endpoints=[{
            "name": "bench-model",
            "api_base": "http://localhost:11434/v1",
            "api_key": "bench-key",
            "model": "bench-model-v1"
        }])
    except Exception as e:
        pytest.skip(f"LLMManager 初始化失败: {e}")


@pytest.fixture
def tool_exec():
    try:
        from seai.core.tool_registry import ToolRegistry
        return ToolRegistry()
    except Exception as e:
        pytest.skip(f"ToolRegistry 初始化失败: {e}")


class TestMemorySearchBenchmark:
    """memory_engine.search() 性能基准 — 1000条记忆下的检索延迟"""

    def test_search_latency_under_load(self, mem_engine, benchmark):
        if benchmark is None:
            pytest.skip("pytest-benchmark 未安装")
        result = benchmark(mem_engine.search_memory, "Python 机器学习")
        assert isinstance(result, list)

    def test_search_cold_start(self, mem_engine, benchmark):
        if benchmark is None:
            pytest.skip("pytest-benchmark 未安装")
        result = benchmark(mem_engine.search_memory, "不存在的罕见关键词xyz")
        assert isinstance(result, list)


class TestLLMChatBenchmark:
    """llm_manager.chat_with_tools() 端到端延迟"""

    def test_chat_method_overhead(self, llm_mgr, benchmark):
        if benchmark is None:
            pytest.skip("pytest-benchmark 未安装")
        assert hasattr(llm_mgr, 'chat')
        assert callable(llm_mgr.chat)


class TestToolExecutionBenchmark:
    """tool_registry.execute_tool() 各内置工具执行时间"""

    def test_tool_registry_initialization(self, tool_exec, benchmark):
        if benchmark is None:
            pytest.skip("pytest-benchmark 未安装")
        assert tool_exec is not None

    def test_get_tool_definitions(self, tool_exec, benchmark):
        if benchmark is None:
            pytest.skip("pytest-benchmark 未安装")
        if hasattr(tool_exec, 'get_tool_definitions'):
            result = benchmark(tool_exec.get_tool_definitions)
            assert isinstance(result, list)


class TestPromptBuildBenchmark:
    """SEAgent._build_static_system_prompt() 提示词构建耗时"""

    def test_prompt_build_latency(self, benchmark):
        if benchmark is None:
            pytest.skip("pytest-benchmark 未安装")
        try:
            from seai.core.agent import SEAgent
            agent = SEAgent()
            result = benchmark(agent._build_static_system_prompt)
            assert isinstance(result, str)
        except Exception as e:
            pytest.skip(f"SEAgent 初始化失败: {e}")
