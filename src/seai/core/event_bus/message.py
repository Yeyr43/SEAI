"""多 Agent 消息数据模型"""
import time
import uuid
from typing import Any, Optional
from dataclasses import dataclass, field


@dataclass
class Message:
    """多 Agent 消息 - 支持任务命名空间和角色路由"""
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task_id: str = ""
    sender: str = ""
    target: Optional[str] = None
    intent: str = ""  # "query", "proposal", "artifact", "review", "command", "heartbeat"
    payload: Any = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "msg_id": self.msg_id,
            "task_id": self.task_id,
            "sender": self.sender,
            "target": self.target,
            "intent": self.intent,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Message":
        return cls(
            msg_id=data.get("msg_id", uuid.uuid4().hex[:12]),
            task_id=data.get("task_id", ""),
            sender=data.get("sender", ""),
            target=data.get("target"),
            intent=data.get("intent", ""),
            payload=data.get("payload"),
            timestamp=data.get("timestamp", time.time()),
        )
