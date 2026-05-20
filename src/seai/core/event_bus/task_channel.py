"""任务命名空间频道 — 按 task_id 隔离的异步消息队列"""
import asyncio
from typing import List
from .message import Message


class TaskChannel:
    """任务命名空间频道 - 按 task_id 隔离的消息队列，支持异步迭代"""

    def __init__(self, task_id: str, maxsize: int = 500):
        self.task_id = task_id
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._history: List[Message] = []
        self._closed = False
        self._max_history = 200

    async def send(self, msg: Message):
        if self._closed:
            raise RuntimeError(f"TaskChannel {self.task_id} 已关闭")
        self._history.append(msg)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        await self._queue.put(msg)

    async def recv(self, timeout: float = None) -> Message:
        if timeout:
            return await asyncio.wait_for(self._queue.get(), timeout=timeout)
        return await self._queue.get()

    def __aiter__(self):
        return self

    async def __anext__(self) -> Message:
        if self._closed and self._queue.empty():
            raise StopAsyncIteration
        try:
            return await asyncio.wait_for(self._queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            if self._closed and self._queue.empty():
                raise StopAsyncIteration
            raise

    async def close(self):
        self._closed = True

    @property
    def history(self) -> List[Message]:
        return list(self._history)

    @property
    def size(self) -> int:
        return self._queue.qsize()
