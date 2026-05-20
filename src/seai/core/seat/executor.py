"""
SEAT Executor Agent — 任务执行者
职责：接收 Commander 任务卡，使用现有 SEAI 工具执行，
      发送心跳，提交审查请求，报告结果
"""
import time
import asyncio
from typing import Optional, Any
from loguru import logger

from .seat_task import (
    TaskCard, TaskStatus, AgentRole,
    EVT_COMMANDER_DISPATCH, EVT_COMMANDER_CANCEL,
    EVT_AGENT_STATUS, EVT_AGENT_RESULT, EVT_AGENT_REQUEST_REVIEW,
    EVT_AGENT_LOG, EVT_INSPECTOR_RESOLUTION,
)
from ..event_bus import AsyncEventBus, Event, EventPriority


class ExecutorAgent:
    """Executor — 执行者，包裹现有 SEAI 工具系统"""

    HEARTBEAT_INTERVAL = 10.0

    def __init__(self, event_bus: AsyncEventBus, tool_executor=None, llm_provider=None, sandbox=None):
        self._event_bus = event_bus
        self._tools = tool_executor
        self._llm = llm_provider
        self._sandbox = sandbox
        self._agent_id = f"executor_{id(self):x}"
        self._current_task: Optional[TaskCard] = None
        self._active = False
        self._task_generation = 0

    async def start(self):
        self._event_bus.subscribe(EVT_COMMANDER_DISPATCH, self._on_dispatch)
        self._event_bus.subscribe(EVT_COMMANDER_CANCEL, self._on_cancel)
        self._event_bus.subscribe(EVT_INSPECTOR_RESOLUTION, self._on_resolution)
        logger.info(f"[SEAT] Executor({self._agent_id}) 已启动")

    async def stop(self):
        self._active = False
        logger.info(f"[SEAT] Executor({self._agent_id}) 已停止")

    async def _on_dispatch(self, event: Event):
        """接收任务卡 → 执行 → 提交审查"""
        data = event.data
        task_id = data.get("task_id", "")
        goal = data.get("goal", "")

        card = TaskCard(
            task_id=task_id,
            goal=goal,
            status=TaskStatus.RUNNING,
            difficulty=data.get("difficulty", "medium"),
            context=data.get("context", {}),
        )
        self._current_task = card
        self._task_generation += 1
        generation = self._task_generation
        self._active = True

        asyncio.create_task(self._execute_with_monitoring(card, generation))

    async def _on_cancel(self, event: Event):
        """取消当前任务"""
        if self._current_task and self._current_task.task_id == event.data.get("task_id"):
            self._active = False
            self._current_task.status = TaskStatus.CANCELLED
            logger.info(f"[SEAT] Executor 任务 {self._current_task.task_id} 已取消")

    async def _on_resolution(self, event: Event):
        """处理外部状态变更"""
        if not self._current_task:
            return
        status = event.data.get("status", "")
        if status in ("completed", "cancelled"):
            self._active = False
        elif status == "blocked":
            await self._emit_heartbeat("blocked", progress_note=event.data.get("reason", ""))

    async def _execute_with_monitoring(self, card: TaskCard, generation: int):
        """执行任务（含心跳循环）"""
        heartbeat_task = asyncio.create_task(self._heartbeat_loop(card.task_id, generation))
        start_time = time.time()

        try:
            result = await self._execute(card)
            elapsed = time.time() - start_time

            if card.status != TaskStatus.CANCELLED:
                await self._emit_result(card.task_id, result, elapsed)
                await self._request_review(card.task_id, result)
        except asyncio.CancelledError:
            logger.info(f"[SEAT] Executor 任务 {card.task_id} 被取消")
        except Exception as e:
            logger.error(f"[SEAT] Executor 执行异常 {card.task_id}: {e}")
            if card.status != TaskStatus.CANCELLED:
                await self._emit_result(card.task_id, f"执行异常: {e}", time.time() - start_time, is_error=True)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            self._active = False

    async def _execute(self, card: TaskCard) -> Any:
        """核心执行逻辑 — 调用 SEAI 工具"""
        goal = card.goal

        if self._sandbox:
            try:
                sandbox_result = await self._sandbox.execute(goal)
                if sandbox_result:
                    return sandbox_result
            except Exception:
                pass

        if self._llm:
            system_prompt = f"""你是 SEAT Executor，当前任务：{goal}

可用的工具将被提供。请分析任务，逐步执行，最终给出结果。

注意：
1. 如果任务涉及文件操作，使用文件工具
2. 如果任务涉及搜索，使用搜索工具
3. 复杂任务拆分为多个步骤
4. 输出最终结果"""
            messages = [{"role": "system", "content": system_prompt}]

            if card.context.get("correction"):
                messages.append({"role": "system", "content": f"修正指示: {card.context['correction']}"})

            messages.append({"role": "user", "content": goal})

            tools = self._collect_tools(goal)
            try:
                response = await self._llm.chat_with_tools(messages, tools, stream=False)
                if isinstance(response, str):
                    return response
                if isinstance(response, dict):
                    return response.get("content", "") or str(response)
            except Exception as e:
                return f"LLM 调用异常: {e}"

        return "Executor: 无可用 LLM 或工具"

    def _collect_tools(self, goal: str) -> list:
        """收集相关工具定义"""
        if not self._tools:
            return []
        try:
            return self._tools.get_tool_definitions()
        except Exception:
            return []

    async def _heartbeat_loop(self, task_id: str, generation: int):
        """定期发送心跳（带代数检查，避免新旧任务心跳冲突）"""
        start = time.time()
        while self._active and generation == self._task_generation:
            elapsed = time.time() - start
            await self._emit_heartbeat("running", elapsed)
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)

    async def _emit_heartbeat(self, status: str, elapsed_seconds: float = 0, progress_note: str = ""):
        event = Event(
            event_type=EVT_AGENT_STATUS,
            source=self._agent_id,
            data={
                "agent_id": self._agent_id,
                "role": AgentRole.EXECUTOR.value,
                "task_id": self._current_task.task_id if self._current_task else "",
                "status": status,
                "elapsed_seconds": elapsed_seconds,
                "progress_note": progress_note,
            },
        )
        await self._event_bus.publish(event)

    async def _emit_result(self, task_id: str, result: Any, elapsed: float, is_error: bool = False):
        event = Event(
            event_type=EVT_AGENT_RESULT,
            source=self._agent_id,
            data={
                "agent_id": self._agent_id,
                "task_id": task_id,
                "summary": str(result)[:500],
                "elapsed_seconds": elapsed,
                "is_error": is_error,
            },
        )
        await self._event_bus.publish(event)

    async def _request_review(self, task_id: str, result: Any):
        event = Event(
            event_type=EVT_AGENT_REQUEST_REVIEW,
            source=self._agent_id,
            data={
                "agent_id": self._agent_id,
                "task_id": task_id,
                "result": str(result)[:1000],
            },
        )
        await self._event_bus.publish(event)
        logger.info(f"[SEAT] Executor 提交审查 {task_id}")

    def get_stats(self) -> dict:
        return {
            "active": self._active,
            "current_task": self._current_task.task_id if self._current_task else None,
        }
