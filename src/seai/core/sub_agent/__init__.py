"""
SEAI 多 Agent 架构 - 子 Agent 系统
支持惰性激活、并行执行、结果压缩、Token 预算管理

此包替代了原来的 core/sub_agent.py 单文件，拆分为 3 个子模块：
- task: AgentRole, SubTask, CompressedResult, TaskComplexityEstimator
- agent_core: BaseSubAgent, SharedFileCache, estimate_query_tokens
- orchestrator: TaskDecomposer, ParallelScheduler, ResultMerger, AgentPool
"""
from .task import (
    AgentRole, SubTask, CompressedResult, TaskComplexityEstimator,
    COMPLEXITY_THRESHOLD, TOKEN_BUDGET_PER_SUB_AGENT,
)
from .agent_core import BaseSubAgent, SharedFileCache, estimate_query_tokens, SUB_AGENT_TIMEOUT
from .orchestrator import TaskDecomposer, ParallelScheduler, ResultMerger, AgentPool, MAX_SUB_AGENTS
