"""异步事件总线 — 发布/订阅 + 多 Agent 消息通道"""
import asyncio
from typing import Dict, List, Callable, Any, Optional, Set
from loguru import logger
from .event import Event, EventPriority
from .message import Message
from .task_channel import TaskChannel
from .event_store import EventStore


class AsyncEventBus:
    """异步事件总线 - 发布/订阅模式，支持通配符匹配 + 多 Agent 消息通道"""

    def __init__(self, max_history: int = 500):
        self._subscribers: Dict[str, List[Callable]] = {}
        self._wildcard_subscribers: List[tuple] = []
        self._history: List[Event] = []
        self._max_history = max_history
        self._processing = False
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._processor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
        self._task_channels: Dict[str, TaskChannel] = {}
        self._message_subscribers: Dict[str, List[Callable]] = {}  # task_id -> handlers
        self._event_store: Optional[EventStore] = None

    def subscribe(self, event_type: str, handler: Callable):
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(handler)

    def subscribe_pattern(self, pattern: str, handler: Callable):
        self._wildcard_subscribers.append((pattern, handler))

    def unsubscribe(self, event_type: str, handler: Callable):
        if event_type in self._subscribers:
            self._subscribers[event_type] = [
                h for h in self._subscribers[event_type] if h != handler
            ]

    async def publish(self, event: Event):
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        await self._queue.put(event)

        async with self._lock:
            if not self._processing:
                self._processing = True
                self._processor_task = asyncio.create_task(self._process_queue())

    async def publish_sync(self, event: Event):
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        await self._dispatch(event)

    async def _process_queue(self):
        try:
            while True:
                try:
                    event = self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                await self._dispatch(event)
        finally:
            async with self._lock:
                self._processing = False
                if not self._queue.empty():
                    self._processing = True
                    self._processor_task = asyncio.create_task(self._process_queue())

    async def _dispatch(self, event: Event):
        handlers: Set[Callable] = set()

        if event.event_type in self._subscribers:
            handlers.update(self._subscribers[event.event_type])

        for pattern, handler in self._wildcard_subscribers:
            if self._match_pattern(event.event_type, pattern):
                handlers.add(handler)

        if not handlers:
            return

        tasks = []
        for handler in handlers:
            tasks.append(self._safe_invoke(handler, event))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _safe_invoke(self, handler: Callable, event: Event):
        try:
            result = handler(event)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"事件处理器异常 [event={event.event_type}, handler={handler.__name__}]: {e}")

    @staticmethod
    def _match_pattern(event_type: str, pattern: str) -> bool:
        if pattern == "*":
            return True
        if pattern.endswith(".*"):
            return event_type.startswith(pattern[:-2])
        if pattern.startswith("*."):
            return event_type.endswith(pattern[2:])
        return event_type == pattern

    def get_history(self, event_type: str = None, limit: int = 50) -> List[Event]:
        if event_type:
            return [e for e in self._history if e.event_type == event_type][-limit:]
        return self._history[-limit:]

    def get_stats(self) -> dict:
        return {
            "total_events": len(self._history),
            "subscriber_count": sum(len(v) for v in self._subscribers.values()),
            "event_types": list(self._subscribers.keys()),
            "wildcard_patterns": len(self._wildcard_subscribers),
            "queue_size": self._queue.qsize(),
            "task_channels": len(self._task_channels),
        }

    # ── 多 Agent 消息通道 API ─────────────────────

    def create_task_channel(self, task_id: str) -> TaskChannel:
        if task_id not in self._task_channels:
            self._task_channels[task_id] = TaskChannel(task_id)
        return self._task_channels[task_id]

    def get_task_channel(self, task_id: str) -> Optional[TaskChannel]:
        return self._task_channels.get(task_id)

    def close_task_channel(self, task_id: str):
        ch = self._task_channels.pop(task_id, None)
        if ch:
            asyncio.create_task(ch.close())

    def subscribe_task(self, task_id: str, handler: Callable):
        if task_id not in self._message_subscribers:
            self._message_subscribers[task_id] = []
        self._message_subscribers[task_id].append(handler)

    def unsubscribe_task(self, task_id: str, handler: Callable):
        if task_id in self._message_subscribers:
            self._message_subscribers[task_id] = [
                h for h in self._message_subscribers[task_id] if h != handler
            ]

    async def publish_message(self, msg: Message) -> bool:
        ch = self._task_channels.get(msg.task_id)
        if ch:
            await ch.send(msg)

        if self._event_store:
            self._event_store.store(msg)

        handlers = self._message_subscribers.get(msg.task_id, []) + \
                   self._message_subscribers.get("*", [])
        for h in handlers:
            try:
                result = h(msg)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"消息处理器异常 [task={msg.task_id}]: {e}")

        return ch is not None

    def enable_persistence(self, db_path: str = None):
        self._event_store = EventStore(db_path)

    def query_messages(self, task_id: str = None, limit: int = 100) -> List[Message]:
        if self._event_store:
            return self._event_store.query(task_id, limit)
        return []

    async def shutdown(self):
        if self._processor_task and not self._processor_task.done():
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        for ch in self._task_channels.values():
            await ch.close()
        self._task_channels.clear()
        if self._event_store:
            self._event_store.close()
