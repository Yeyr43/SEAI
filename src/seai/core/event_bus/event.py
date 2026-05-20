"""
事件数据模型 — Event 和 EventPriority
"""
import time
import uuid
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum


class EventPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


@dataclass
class Event:
    event_type: str
    source: str
    data: Dict[str, Any] = field(default_factory=dict)
    priority: EventPriority = EventPriority.NORMAL
    event_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: float = field(default_factory=time.time)
    correlation_id: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "source": self.source,
            "data": self.data,
            "priority": self.priority.value,
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
        }
