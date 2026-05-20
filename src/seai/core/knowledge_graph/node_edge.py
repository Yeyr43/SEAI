"""知识图谱节点与边的数据模型"""
import time
from datetime import datetime, timezone
from typing import List, Optional
from dataclasses import dataclass, field


@dataclass
class KnowledgeNode:
    id: str
    text: str
    node_type: str = "concept"
    importance: float = 1.0
    access_count: int = 0
    last_access: float = field(default_factory=time.time)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    entities: List[str] = field(default_factory=list)
    version: int = 1
    previous_version_id: Optional[str] = None


@dataclass
class KnowledgeEdge:
    source: str
    target: str
    relation: str = "related"
    weight: float = 1.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
