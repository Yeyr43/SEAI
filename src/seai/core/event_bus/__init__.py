"""
SEAI 异步事件总线 — 解耦模块间通信
支持发布/订阅模式、通配符匹配、异步处理、事件溯源

此包替代了原来的 core/event_bus.py 单文件，拆分为 5 个子模块：
- event: Event, EventPriority
- message: Message
- task_channel: TaskChannel
- event_store: EventStore
- bus: AsyncEventBus
"""
from .event import Event, EventPriority
from .message import Message
from .task_channel import TaskChannel
from .event_store import EventStore
from .bus import AsyncEventBus

# 全局单例
event_bus = AsyncEventBus()
