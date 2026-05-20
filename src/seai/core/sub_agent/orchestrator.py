"""
子 Agent 编排器 — TaskDecomposer, ParallelScheduler, ResultMerger, AgentPool
"""
import asyncio
import json
import time
from typing import Dict, List, Any, Callable
from loguru import logger
from .task import AgentRole, SubTask, CompressedResult, COMPLEXITY_THRESHOLD, TaskComplexityEstimator
from .agent_core import BaseSubAgent, SharedFileCache

MAX_SUB_AGENTS = 3


class TaskDecomposer:
    """任务分解器 - 将复杂任务拆分为子任务"""

    DECOMPOSE_PROMPT = """你是任务分解器。分析以下用户请求并分解为子任务。

用户请求：{query}

可用 Agent 类型：
- explorer: 搜索信息、读取文件、收集数据
- coder: 代码生成、Bug 修复、测试编写
- reviewer: 代码审查、质量验证
- test_runner: 测试执行、结果分析

输出 JSON 格式：
{{
  "strategy": "direct" 或 "delegate",
  "reason": "判断理由",
  "subtasks": [
    {{
      "agent": "explorer|coder|reviewer|test_runner",
      "description": "子任务描述",
      "context": "需要的上下文信息",
      "depends_on": []
    }}
  ]
}}

分解规则：
1. 如果任务简单（只需回答问题/单步操作），strategy 为 "direct"，subtasks 为空
2. 子任务按依赖关系排序，无依赖的子任务可并行执行
3. 每个子任务描述要具体、可执行
4. depends_on 填写依赖的子任务索引（从 0 开始）

只输出 JSON，不要解释。"""

    def __init__(self, llm_provider=None):
        self.llm_provider = llm_provider

    async def decompose(self, query: str) -> dict:
        if not self.llm_provider:
            return self._rule_based_decompose(query)
        prompt = self.DECOMPOSE_PROMPT.format(query=query)
        try:
            response = await self.llm_provider.chat([{"role": "user", "content": prompt}])
            import re
            json_match = re.search(r'\{[\s\S]*\}', response if isinstance(response, str) else response.get("content", ""))
            if json_match:
                return json.loads(json_match.group(0))
        except Exception as e:
            logger.warning(f"LLM 任务分解失败，使用规则分解: {e}")
        return self._rule_based_decompose(query)

    def _rule_based_decompose(self, query: str) -> dict:
        estimator = TaskComplexityEstimator()
        complexity = estimator.estimate(query)
        if complexity < COMPLEXITY_THRESHOLD:
            return {"strategy": "direct", "reason": "任务简单，直接处理", "subtasks": []}
        query_lower = query.lower()
        subtasks = []
        has_search = any(kw in query_lower for kw in ["搜索", "查找", "研究", "分析"])
        has_code = any(kw in query_lower for kw in ["写", "创建", "实现", "修复", "代码", "生成"])
        has_test = any(kw in query_lower for kw in ["测试", "验证", "检查"])
        if has_search:
            subtasks.append({"agent": "explorer", "description": f"搜索和收集信息: {query[:200]}", "context": "", "depends_on": []})
        if has_code:
            deps = [0] if has_search else []
            subtasks.append({"agent": "coder", "description": f"生成/修改代码: {query[:200]}", "context": "使用探索阶段收集的信息", "depends_on": deps})
        if has_test and has_code:
            subtasks.append({"agent": "test_runner", "description": "执行测试并验证结果", "context": "测试编码阶段生成的代码", "depends_on": [len(subtasks) - 1]})
        if not subtasks:
            return {"strategy": "direct", "reason": "无法分解，直接处理", "subtasks": []}
        return {"strategy": "delegate", "reason": "规则分解", "subtasks": subtasks}


class ParallelScheduler:
    """并行调度器 - 管理子任务的并行执行"""

    def __init__(self, max_concurrent: int = MAX_SUB_AGENTS):
        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def execute(self, subtasks: List[SubTask], executor: Callable[[SubTask], Any]) -> List[SubTask]:
        dependency_groups = self._group_by_dependency(subtasks)
        completed: Dict[int, SubTask] = {}
        for group in dependency_groups:
            async def run_one(task: SubTask):
                async with self._semaphore:
                    task.result = await executor(task)
                    return task

            tasks_in_group = [t for t in group]
            results = await asyncio.gather(*[run_one(t) for t in tasks_in_group], return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    tasks_in_group[i].result = CompressedResult(
                        agent_role=tasks_in_group[i].agent_role, agent_id=tasks_in_group[i].task_id,
                        status="error", summary=f"并行执行异常: {result}",
                    )
                completed[tasks_in_group[i].task_id] = tasks_in_group[i]
        return [completed.get(t.task_id, t) for t in subtasks]

    def _group_by_dependency(self, subtasks: List[SubTask]) -> List[List[SubTask]]:
        groups = []
        remaining = list(subtasks)
        completed_ids = set()
        while remaining:
            current_group = []
            still_remaining = []
            for task in remaining:
                deps_met = all(dep_id in completed_ids for dep_id in task.depends_on)
                if deps_met:
                    current_group.append(task)
                else:
                    still_remaining.append(task)
            if not current_group and still_remaining:
                current_group = still_remaining
                still_remaining = []
            groups.append(current_group)
            for t in current_group:
                completed_ids.add(t.task_id)
            remaining = still_remaining
        return groups


class ResultMerger:
    """结果合并器 - 将子 Agent 结果合并为统一响应"""

    MERGE_PROMPT = """你是结果合并器。将以下子 Agent 的执行结果综合为一个连贯的回复。

原始用户请求：{query}

子 Agent 执行结果：
{results}

请综合所有结果，生成一个清晰、完整的回复。格式：
1. 首先概述完成的工作
2. 然后分点说明关键发现/变更
3. 如有警告或问题，明确提示

直接输出回复文本，不要 JSON 格式。"""

    def __init__(self, llm_provider=None):
        self.llm_provider = llm_provider

    async def merge(self, query: str, results: List[CompressedResult]) -> str:
        if not results:
            return "无子 Agent 执行结果"
        successful = [r for r in results if r.status == "success"]
        failed = [r for r in results if r.status != "success"]
        if not successful and failed:
            errors = "\n".join(f"- {r.agent_role.value}: {r.summary}" for r in failed)
            return f"所有子任务执行失败：\n{errors}"
        if len(results) == 1 and results[0].status == "success":
            return results[0].summary
        if self.llm_provider:
            try:
                results_text = "\n\n".join(
                    f"### {r.agent_role.value} Agent\n状态: {r.status}\n摘要: {r.summary}\n文件变更: {r.files_changed}\n警告: {r.warnings}"
                    for r in results
                )
                response = await self.llm_provider.chat([{"role": "user", "content": self.MERGE_PROMPT.format(query=query, results=results_text)}])
                return response if isinstance(response, str) else response.get("content", "")
            except Exception as e:
                logger.warning(f"LLM 合并失败，使用简单合并: {e}")
        parts = [f"**【{r.agent_role.value}】** {r.summary}" for r in successful]
        if failed:
            parts.append("\n**警告：**")
            for r in failed:
                parts.append(f"- {r.agent_role.value}: {r.summary}")
        return "\n\n".join(parts)


class AgentPool:
    """Agent 池管理器 - 创建、复用和销毁子 Agent"""

    def __init__(self, llm_provider=None, tool_executor=None, max_agents: int = MAX_SUB_AGENTS):
        self.llm_provider = llm_provider
        self.tool_executor = tool_executor
        self.max_agents = max_agents
        self.file_cache = SharedFileCache()
        self._pool: Dict[str, BaseSubAgent] = {}
        self._stats: Dict[str, dict] = {}

    def acquire(self, role: AgentRole) -> BaseSubAgent:
        agent = BaseSubAgent(role=role, llm_provider=self.llm_provider,
                             tool_executor=self.tool_executor, file_cache=self.file_cache)
        self._pool[agent.agent_id] = agent
        self._stats[agent.agent_id] = {"role": role.value, "created_at": time.time(), "task_count": 0}
        return agent

    def release(self, agent_id: str):
        if agent_id in self._pool:
            del self._pool[agent_id]

    def get_stats(self) -> dict:
        return {"active_agents": len(self._pool), "file_cache_entries": len(self.file_cache._cache), "agent_stats": self._stats}

    def clear_cache(self):
        self.file_cache.clear()
