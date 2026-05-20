"""
子 Agent 任务数据结构 — SubTask, CompressedResult, TaskComplexityEstimator
"""
import uuid
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from enum import Enum


class AgentRole(str, Enum):
    ORCHESTRATOR = "orchestrator"
    EXPLORER = "explorer"
    CODER = "coder"
    REVIEWER = "reviewer"
    TEST_RUNNER = "test_runner"


COMPLEXITY_THRESHOLD = 0.5
TOKEN_BUDGET_PER_SUB_AGENT = 3000


@dataclass
class CompressedResult:
    agent_role: AgentRole
    agent_id: str
    status: str
    summary: str
    files_changed: List[str] = field(default_factory=list)
    test_results: Dict[str, int] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    data: Dict[str, any] = field(default_factory=dict)
    token_used: int = 0
    elapsed_ms: float = 0

    def to_dict(self) -> dict:
        return {
            "agent_role": self.agent_role.value,
            "agent_id": self.agent_id,
            "status": self.status,
            "summary": self.summary,
            "files_changed": self.files_changed,
            "test_results": self.test_results,
            "warnings": self.warnings,
            "data": self.data,
            "token_used": self.token_used,
            "elapsed_ms": self.elapsed_ms,
        }


@dataclass
class SubTask:
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    agent_role: AgentRole = AgentRole.EXPLORER
    description: str = ""
    context: str = ""
    depends_on: List[str] = field(default_factory=list)
    max_tokens: int = TOKEN_BUDGET_PER_SUB_AGENT
    result: Optional[CompressedResult] = None


class TaskComplexityEstimator:
    """任务复杂度评估器 - 决定是否激活多 Agent 模式"""

    COMPLEXITY_INDICATORS = {
        "multi_file": ["所有文件", "每个文件", "src/", "整个项目", "批量", "全部"],
        "multi_step": ["先", "然后", "接着", "最后", "步骤", "首先"],
        "code_gen": ["写一个", "创建", "实现", "开发", "构建", "生成代码"],
        "search_analyze": ["搜索并", "查找并", "分析并", "研究"],
        "fix_test": ["修复", "调试", "测试", "bug", "错误", "问题"],
        "high_complexity": ["API", "数据库", "认证", "部署", "架构", "重构"],
    }

    def __init__(self, threshold: float = COMPLEXITY_THRESHOLD):
        self.threshold = threshold

    def estimate(self, query: str, history: List[Dict] = None) -> float:
        query_lower = query.lower()
        scores = []

        for category, indicators in self.COMPLEXITY_INDICATORS.items():
            match_count = sum(1 for kw in indicators if kw.lower() in query_lower)
            if match_count > 0:
                if category == "high_complexity":
                    scores.append(min(match_count * 0.3, 1.0))
                elif category == "multi_file":
                    scores.append(min(match_count * 0.25, 0.75))
                elif category in ("code_gen", "fix_test"):
                    scores.append(min(match_count * 0.2, 0.6))
                else:
                    scores.append(min(match_count * 0.15, 0.45))

        history_bonus = 0.0
        if history:
            history_len = len(history)
            if history_len > 20:
                history_bonus = 0.2
            elif history_len > 10:
                history_bonus = 0.1

        base_score = sum(scores) / len(scores) if scores else 0.0
        final_score = min(base_score + history_bonus, 1.0)

        return final_score

    def should_delegate(self, query: str, history: List[Dict] = None) -> bool:
        return self.estimate(query, history) >= self.threshold
