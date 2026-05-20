"""
SEAT 任务协议 — 任务卡、状态机、消息类型定义
"""
import uuid
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    BLOCKED = "blocked"
    NEED_RESOURCE = "need_resource"
    DEADLOCK = "deadlock"
    OUT_OF_SCOPE = "out_of_scope"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class AgentRole(str, Enum):
    COMMANDER = "commander"
    INSPECTOR = "inspector"
    EXECUTOR = "executor"


# ── EventBus 事件类型 ──

EVT_COMMANDER_DISPATCH = "seat.commander.dispatch"
EVT_COMMANDER_CANCEL = "seat.commander.cancel"
EVT_COMMANDER_AWAKE = "seat.commander.awake"
EVT_COMMANDER_ARBITRATE = "seat.commander.arbitrate"

EVT_INSPECTOR_REPORT = "seat.inspector.report"
EVT_INSPECTOR_RESOLUTION = "seat.inspector.resolution"
EVT_INSPECTOR_EVOLVE_PROPOSAL = "seat.inspector.evolve_proposal"

EVT_AGENT_STATUS = "seat.agent.status"
EVT_AGENT_RESULT = "seat.agent.result"
EVT_AGENT_REQUEST_REVIEW = "seat.agent.request_review"
EVT_AGENT_LOG = "seat.agent.log"


# ── 难度等级 ──

class DifficultyLevel(str, Enum):
    TRIVIAL = "trivial"
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    COMPLEX = "complex"


# ── 核心数据类 ──

@dataclass
class TaskCard:
    """任务卡 — Commander 下发的唯一定义"""
    task_id: str = field(default_factory=lambda: f"seat_{int(time.time())}_{uuid.uuid4().hex[:6]}")
    goal: str = ""
    difficulty: DifficultyLevel = DifficultyLevel.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    agent_roles: List[AgentRole] = field(default_factory=lambda: [AgentRole.EXECUTOR])
    context: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    parent_task_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "difficulty": self.difficulty.value,
            "status": self.status.value,
            "agent_roles": [r.value for r in self.agent_roles],
            "context": self.context,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
            "parent_task_id": self.parent_task_id,
        }


@dataclass
class AgentHeartbeat:
    """Agent 心跳"""
    agent_id: str
    role: AgentRole
    task_id: str
    status: str
    elapsed_seconds: float = 0.0
    progress_note: str = ""
    timestamp: float = field(default_factory=time.time)


@dataclass
class InspectorReport:
    """Inspector 审查报告"""
    task_id: str
    approved: bool
    summary: str
    issues: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)
