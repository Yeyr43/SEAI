"""
SEAI 统一消息协议 — 多 Agent 通信的基础数据类型

定义 SEAT（多智能体协作系统）中所有模块使用的标准消息格式。
与 event_bus.py 配合使用，支持任务隔离、心跳监控、消息路由。
"""
from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum
import uuid
import time


class TaskStatus(str, Enum):
    ON_TRACK = "on_track"
    NEED_RESOURCE = "need_resource"
    DEADLOCK = "deadlock"
    OUT_OF_SCOPE = "out_of_scope"
    COMPLETED = "completed"


@dataclass
class TaskCard:
    """Commander 发放的任务卡片，描述一个完整的任务单元"""
    task_id: str
    description: str
    difficulty_level: int  # 1-4，对应 TDE 评分
    required_capabilities: list = field(default_factory=list)
    initial_agents: list = field(default_factory=list)
    completion_criteria: str = ""
    timeout: int = 300  # 秒

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "difficulty_level": self.difficulty_level,
            "required_capabilities": self.required_capabilities,
            "initial_agents": self.initial_agents,
            "completion_criteria": self.completion_criteria,
            "timeout": self.timeout,
        }


@dataclass
class Heartbeat:
    """Agent 定期发送的心跳，供 Inspector 监控"""
    agent_id: str
    task_id: str
    progress_summary: str = ""
    next_step: str = ""
    confidence: float = 1.0
    status: TaskStatus = TaskStatus.ON_TRACK
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "progress_summary": self.progress_summary,
            "next_step": self.next_step,
            "confidence": self.confidence,
            "status": self.status.value,
            "timestamp": self.timestamp,
        }


@dataclass
class AgentMessage:
    """Agent 间通信的标准消息"""
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    sender: str = ""
    target: Optional[str] = None  # None = 广播给同一 task 的所有 agent
    intent: str = ""  # "query", "proposal", "artifact", "review", "command"
    content: Any = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "task_id": self.task_id,
            "sender": self.sender,
            "target": self.target,
            "intent": self.intent,
            "content": self.content,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AgentMessage":
        return cls(
            msg_id=data.get("msg_id", uuid.uuid4().hex[:12]),
            task_id=data.get("task_id", ""),
            sender=data.get("sender", ""),
            target=data.get("target"),
            intent=data.get("intent", ""),
            content=data.get("content"),
            timestamp=data.get("timestamp", time.time()),
        )


@dataclass
class EvolutionSignal:
    """持续进化模块的内部信号"""
    target: str  # "skill:xyz", "tool:abc", "memory:id"
    suggested_change: dict
    source_agent: str = ""
    confidence: float = 0.5

    def to_dict(self) -> dict:
        return {
            "target": self.target,
            "suggested_change": self.suggested_change,
            "source_agent": self.source_agent,
            "confidence": self.confidence,
        }
