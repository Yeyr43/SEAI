"""
SEAI 子 Agent 系统单元测试
覆盖：复杂度评估、Agent 池、任务分解、并行调度、结果合并、Token 预算
"""
import asyncio
import json
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path

from seai.core.sub_agent import (
    AgentRole, BaseSubAgent, AgentPool, TaskComplexityEstimator,
    TaskDecomposer, ParallelScheduler, ResultMerger,
    SubTask, CompressedResult, SharedFileCache,
    COMPLEXITY_THRESHOLD, TOKEN_BUDGET_PER_SUB_AGENT, MAX_SUB_AGENTS,
)


class TestTaskComplexityEstimator:

    def test_simple_query_below_threshold(self):
        estimator = TaskComplexityEstimator(threshold=0.5)
        score = estimator.estimate("今天星期几")
        assert score < 0.5
        assert not estimator.should_delegate("今天星期几")

    def test_complex_query_above_threshold(self):
        estimator = TaskComplexityEstimator(threshold=0.3)
        score = estimator.estimate("分析 src/ 目录下所有 Python 文件，找出 bug 并修复，然后写测试")
        assert score >= 0.3
        assert estimator.should_delegate("分析 src/ 目录下所有 Python 文件，找出 bug 并修复，然后写测试")

    def test_moderate_query_near_threshold(self):
        estimator = TaskComplexityEstimator(threshold=0.5)
        score = estimator.estimate("搜索 Python async 最佳实践并总结")
        assert 0.0 <= score <= 1.0

    def test_history_bonus(self):
        estimator = TaskComplexityEstimator(threshold=0.5)
        history = [{"role": "user", "content": f"msg{i}"} for i in range(25)]
        score_with = estimator.estimate("写一个函数", history=history)
        score_without = estimator.estimate("写一个函数")
        assert score_with >= score_without

    def test_empty_query(self):
        estimator = TaskComplexityEstimator(threshold=0.5)
        score = estimator.estimate("")
        assert score == 0.0
        assert not estimator.should_delegate("")

    def test_high_complexity_keywords(self):
        estimator = TaskComplexityEstimator(threshold=0.3)
        score = estimator.estimate("构建一个完整的 REST API 架构，包含认证和数据库")
        assert score >= 0.6

    def test_custom_threshold(self):
        estimator_low = TaskComplexityEstimator(threshold=0.1)
        estimator_high = TaskComplexityEstimator(threshold=0.9)
        query = "搜索信息"
        score = estimator_low.estimate(query)
        assert estimator_low.should_delegate(query) == (score >= 0.1)
        assert not estimator_high.should_delegate(query)


class TestSharedFileCache:

    def test_set_and_get(self):
        cache = SharedFileCache()
        cache.set("/tmp/test.py", "print('hello')")
        assert cache.get("/tmp/test.py") == "print('hello')"

    def test_cache_miss(self):
        cache = SharedFileCache()
        assert cache.get("/nonexistent.py") is None

    def test_ttl_expiry(self):
        cache = SharedFileCache(ttl_seconds=0.01)
        cache.set("/tmp/test.py", "data")
        time.sleep(0.02)
        assert cache.get("/tmp/test.py") is None

    def test_max_entries_eviction(self):
        cache = SharedFileCache(max_entries=3)
        for i in range(5):
            cache.set(f"/tmp/file{i}.py", f"content{i}")
        assert len(cache._cache) <= 3

    def test_clear(self):
        cache = SharedFileCache()
        cache.set("/tmp/a.py", "a")
        cache.set("/tmp/b.py", "b")
        cache.clear()
        assert len(cache._cache) == 0


class TestBaseSubAgent:

    def test_build_system_prompt(self):
        agent = BaseSubAgent(role=AgentRole.EXPLORER)
        prompt = agent._build_system_prompt("搜索文件", "上下文信息")
        assert "探索 Agent" in prompt
        assert "搜索文件" in prompt
        assert "上下文信息" in prompt

    def test_filter_tools(self):
        agent = BaseSubAgent(role=AgentRole.CODER)
        all_tools = [
            {"function": {"name": "read_file"}},
            {"function": {"name": "write_file"}},
            {"function": {"name": "web_search"}},
            {"function": {"name": "delete_file"}},
        ]
        filtered = agent._filter_tools(all_tools)
        names = [t["function"]["name"] for t in filtered]
        assert "read_file" in names
        assert "write_file" in names
        assert "web_search" not in names

    def test_filter_tools_empty_allowed(self):
        class FakeAgent(BaseSubAgent):
            pass

        fake = FakeAgent(role=AgentRole.REVIEWER)
        fake.ROLE_TOOLS = {AgentRole.REVIEWER: []}
        all_tools = [{"function": {"name": "read_file"}}]
        filtered = fake._filter_tools(all_tools)
        assert len(filtered) == 0

    @pytest.mark.asyncio
    async def test_execute_without_llm(self):
        agent = BaseSubAgent(role=AgentRole.EXPLORER)
        result = await agent.execute("搜索测试")
        assert result.status == "error"
        assert "未初始化" in result.summary

    @pytest.mark.asyncio
    async def test_execute_with_mock_llm(self):
        mock_llm = MagicMock()
        mock_llm.chat_with_tools = AsyncMock(return_value="测试响应结果")

        mock_tools = MagicMock()
        mock_tools.get_tool_definitions = MagicMock(return_value=[
            {"function": {"name": "read_file"}},
            {"function": {"name": "web_search"}},
        ])

        agent = BaseSubAgent(
            role=AgentRole.EXPLORER,
            llm_provider=mock_llm,
            tool_executor=mock_tools,
        )
        result = await agent.execute("搜索测试")
        assert result.status == "success"
        assert "测试响应结果" in result.summary
        assert result.agent_role == AgentRole.EXPLORER
        assert result.token_used > 0
        assert result.elapsed_ms > 0

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        mock_llm = MagicMock()
        async def slow_response(*args, **kwargs):
            await asyncio.sleep(999)
            return "slow"
        mock_llm.chat_with_tools = slow_response

        agent = BaseSubAgent(role=AgentRole.EXPLORER, llm_provider=mock_llm)
        with patch("seai.core.sub_agent.SUB_AGENT_TIMEOUT", 0.01):
            result = await agent.execute("测试")
        assert result.status == "timeout"

    def test_parse_json_response(self):
        agent = BaseSubAgent(role=AgentRole.CODER)
        result = agent._parse_json_response('{"status": "success", "summary": "完成"}')
        assert result["status"] == "success"
        assert result["summary"] == "完成"

    def test_parse_json_response_malformed(self):
        agent = BaseSubAgent(role=AgentRole.CODER)
        result = agent._parse_json_response("这不是 JSON")
        assert result["status"] == "success"

    def test_compressed_result_to_dict(self):
        result = CompressedResult(
            agent_role=AgentRole.CODER, agent_id="test123",
            status="success", summary="完成测试",
            files_changed=["a.py"], test_results={"passed": 3},
            token_used=500, elapsed_ms=1200,
        )
        d = result.to_dict()
        assert d["agent_role"] == "coder"
        assert d["summary"] == "完成测试"
        assert d["files_changed"] == ["a.py"]


class TestTaskDecomposer:

    @pytest.mark.asyncio
    async def test_decompose_simple_query(self):
        decomposer = TaskDecomposer(llm_provider=None)
        plan = await decomposer.decompose("今天星期几")
        assert plan["strategy"] == "direct"
        assert len(plan.get("subtasks", [])) == 0

    @pytest.mark.asyncio
    async def test_decompose_complex_query_rule_based(self):
        decomposer = TaskDecomposer(llm_provider=None)
        plan = await decomposer.decompose("先搜索所有 Python 文件，分析代码问题，然后修复 bug，最后编写测试")
        assert plan["strategy"] == "delegate"
        assert len(plan["subtasks"]) >= 2

    @pytest.mark.asyncio
    async def test_decompose_with_llm(self):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value=json.dumps({
            "strategy": "delegate", "reason": "复杂任务",
            "subtasks": [
                {"agent": "explorer", "description": "搜索信息", "context": "", "depends_on": []},
                {"agent": "coder", "description": "编写代码", "context": "", "depends_on": [0]},
            ]
        }))
        decomposer = TaskDecomposer(llm_provider=mock_llm)
        plan = await decomposer.decompose("搜索所有文件并实现 REST API 并且修复 bug")
        assert plan["strategy"] == "delegate"
        assert len(plan["subtasks"]) == 2

    @pytest.mark.asyncio
    async def test_decompose_llm_fallback(self):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(side_effect=Exception("LLM 错误"))
        decomposer = TaskDecomposer(llm_provider=mock_llm)
        plan = await decomposer.decompose("先搜索文件，分析问题，然后写代码修复，最后写测试验证")
        assert plan["strategy"] == "delegate"


class TestParallelScheduler:

    @pytest.mark.asyncio
    async def test_sequential_tasks(self):
        scheduler = ParallelScheduler(max_concurrent=2)
        t1 = SubTask(agent_role=AgentRole.EXPLORER, description="任务1")
        t2 = SubTask(agent_role=AgentRole.CODER, description="任务2", depends_on=[t1.task_id])

        async def executor(task):
            return CompressedResult(
                agent_role=task.agent_role, agent_id=task.task_id,
                status="success", summary=f"完成: {task.description}",
            )
        results = await scheduler.execute([t1, t2], executor)
        assert len(results) == 2
        assert results[0].result.status == "success"
        assert results[1].result.status == "success"

    @pytest.mark.asyncio
    async def test_parallel_tasks(self):
        scheduler = ParallelScheduler(max_concurrent=3)
        tasks = [SubTask(agent_role=AgentRole.EXPLORER, description=f"任务{i}") for i in range(2)]
        start_times = []

        async def executor(task):
            start_times.append(time.time())
            await asyncio.sleep(0.05)
            return CompressedResult(
                agent_role=task.agent_role, agent_id=task.task_id,
                status="success", summary=f"完成: {task.description}",
            )
        results = await scheduler.execute(tasks, executor)
        assert len(results) == 2
        assert all(r.result.status == "success" for r in results)
        if len(start_times) >= 2:
            diff = abs(start_times[0] - start_times[1])
            assert diff < 0.2

    @pytest.mark.asyncio
    async def test_executor_exception(self):
        scheduler = ParallelScheduler()
        t1 = SubTask(agent_role=AgentRole.EXPLORER, description="会失败的任务")

        async def failing_executor(task):
            raise RuntimeError("模拟执行失败")
        results = await scheduler.execute([t1], failing_executor)
        assert results[0].result.status == "error"
        assert "模拟执行失败" in results[0].result.summary

    def test_group_by_dependency(self):
        scheduler = ParallelScheduler()
        t0 = SubTask(task_id="0", agent_role=AgentRole.EXPLORER, description="t0")
        t1 = SubTask(task_id="1", agent_role=AgentRole.CODER, description="t1", depends_on=["0"])
        t2 = SubTask(task_id="2", agent_role=AgentRole.EXPLORER, description="t2", depends_on=["0"])
        t3 = SubTask(task_id="3", agent_role=AgentRole.REVIEWER, description="t3", depends_on=["1", "2"])
        groups = scheduler._group_by_dependency([t3, t2, t1, t0])
        ids_by_group = [[t.task_id for t in g] for g in groups]
        assert "0" in ids_by_group[0]
        assert "1" in ids_by_group[1] and "2" in ids_by_group[1]
        assert "3" in ids_by_group[2]


class TestResultMerger:

    @pytest.mark.asyncio
    async def test_merge_empty(self):
        merger = ResultMerger()
        result = await merger.merge("查询", [])
        assert "无子 Agent 执行结果" in result

    @pytest.mark.asyncio
    async def test_merge_single_result(self):
        merger = ResultMerger()
        results = [CompressedResult(
            agent_role=AgentRole.EXPLORER, agent_id="1",
            status="success", summary="找到 3 个相关文件",
        )]
        result = await merger.merge("查询", results)
        assert "找到 3 个相关文件" in result

    @pytest.mark.asyncio
    async def test_merge_multiple_results(self):
        merger = ResultMerger()
        results = [
            CompressedResult(agent_role=AgentRole.EXPLORER, agent_id="1", status="success", summary="搜索完成"),
            CompressedResult(agent_role=AgentRole.CODER, agent_id="2", status="success", summary="代码生成完成", files_changed=["a.py"]),
        ]
        result = await merger.merge("查询", results)
        assert "explorer" in result.lower() or "探索" in result
        assert "coder" in result.lower() or "编码" in result

    @pytest.mark.asyncio
    async def test_merge_with_failures(self):
        merger = ResultMerger()
        results = [
            CompressedResult(agent_role=AgentRole.EXPLORER, agent_id="1", status="success", summary="搜索完成"),
            CompressedResult(agent_role=AgentRole.CODER, agent_id="2", status="error", summary="代码生成失败"),
        ]
        result = await merger.merge("查询", results)
        assert "警告" in result

    @pytest.mark.asyncio
    async def test_merge_all_failed(self):
        merger = ResultMerger()
        results = [CompressedResult(agent_role=AgentRole.EXPLORER, agent_id="1", status="error", summary="搜索失败")]
        result = await merger.merge("查询", results)
        assert "失败" in result

    @pytest.mark.asyncio
    async def test_merge_with_llm(self):
        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(return_value="综合结果：任务成功完成")
        merger = ResultMerger(llm_provider=mock_llm)
        results = [
            CompressedResult(agent_role=AgentRole.EXPLORER, agent_id="1", status="success", summary="搜索完成"),
            CompressedResult(agent_role=AgentRole.CODER, agent_id="2", status="success", summary="代码生成完成"),
        ]
        result = await merger.merge("查询", results)
        assert "任务成功完成" in result


class TestAgentPool:

    def test_acquire_and_release(self):
        pool = AgentPool()
        agent = pool.acquire(AgentRole.EXPLORER)
        assert agent.role == AgentRole.EXPLORER
        assert agent.agent_id in pool._pool
        pool.release(agent.agent_id)
        assert agent.agent_id not in pool._pool

    def test_pool_stats(self):
        pool = AgentPool()
        agent = pool.acquire(AgentRole.CODER)
        stats = pool.get_stats()
        assert stats["active_agents"] == 1
        assert isinstance(stats["file_cache_entries"], int)

    def test_file_cache_shared(self):
        pool = AgentPool()
        agent1 = pool.acquire(AgentRole.EXPLORER)
        agent2 = pool.acquire(AgentRole.CODER)
        agent1.file_cache.set("/shared.py", "shared content")
        assert agent2.file_cache.get("/shared.py") == "shared content"

    def test_clear_cache(self):
        pool = AgentPool()
        agent = pool.acquire(AgentRole.EXPLORER)
        agent.file_cache.set("/test.py", "data")
        pool.clear_cache()
        assert agent.file_cache.get("/test.py") is None


class TestSubTask:
    def test_subtask_defaults(self):
        task = SubTask(agent_role=AgentRole.EXPLORER, description="测试任务")
        assert task.agent_role == AgentRole.EXPLORER
        assert task.description == "测试任务"
        assert task.result is None
        assert len(task.task_id) == 8

    def test_subtask_dependencies(self):
        task = SubTask(agent_role=AgentRole.CODER, description="编码任务", depends_on=["abc123", "def456"])
        assert len(task.depends_on) == 2
        assert "abc123" in task.depends_on


class TestTokenEstimation:
    def test_estimate_query_tokens(self):
        from seai.core.sub_agent import estimate_query_tokens
        tokens = estimate_query_tokens("hello world", "system prompt here", [])
        assert tokens > 0

    def test_token_budget_constants(self):
        assert TOKEN_BUDGET_PER_SUB_AGENT == 3000
        assert MAX_SUB_AGENTS == 3
        assert COMPLEXITY_THRESHOLD == 0.5