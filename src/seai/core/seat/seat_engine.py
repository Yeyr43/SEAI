"""
SEAT Engine — 自进化多 Agent 团队主引擎
编排 Commander + Inspector + Executor 三 Agent 闭环
"""
import asyncio
import time
from typing import Optional, Dict, Any
from loguru import logger

from .seat_task import TaskCard, TaskStatus
from .commander import CommanderAgent
from .inspector import InspectorAgent
from .executor import ExecutorAgent
from ..event_bus import AsyncEventBus, event_bus
from ..feedback_loop import FeedbackLoop, FeedbackSource, FeedbackSeverity
from ..interfaces.llm_provider import LLMProvider
from ..interfaces.tool_executor import ToolExecutor


class SEATEngine:
    """SEAT Engine — 三 Agent 闭环编排"""

    def __init__(
        self,
        llm_provider: LLMProvider = None,
        tool_executor: ToolExecutor = None,
        sandbox=None,
        feedback_loop: FeedbackLoop = None,
        complexity_estimator=None,
        event_bus_instance: AsyncEventBus = None,
    ):
        self._event_bus = event_bus_instance or event_bus
        self._feedback_loop = feedback_loop
        self._initialized = False

        self.commander = CommanderAgent(
            event_bus=self._event_bus,
            llm_provider=llm_provider,
            complexity_estimator=complexity_estimator,
        )
        self.inspector = InspectorAgent(
            event_bus=self._event_bus,
            llm_provider=llm_provider,
        )
        self.executor = ExecutorAgent(
            event_bus=self._event_bus,
            tool_executor=tool_executor,
            llm_provider=llm_provider,
            sandbox=sandbox,
        )

    async def start(self):
        """启动三 Agent"""
        await self.commander.start()
        await self.inspector.start()
        await self.executor.start()
        self._initialized = True
        logger.info("[SEAT] 三 Agent 闭环已启动")

    async def stop(self):
        """停止三 Agent"""
        await self.executor.stop()
        await self.inspector.stop()
        await self.commander.stop()
        self._initialized = False
        logger.info("[SEAT] 三 Agent 闭环已停止")

    async def submit_task(self, goal: str, context: dict = None) -> dict:
        """提交任务到 SEAT 系统"""
        if not self._initialized:
            raise RuntimeError("SEAT Engine 未初始化")

        card = await self.commander.submit_task(goal, context)
        if self._feedback_loop:
            self._feedback_loop.emit(
                source=FeedbackSource.EVOLUTION_RESULT,
                title=f"SEAT 新任务: {goal[:60]}",
                detail=f"task_id={card.task_id}, difficulty={card.difficulty.value}",
                metadata={"task_id": card.task_id},
                severity=FeedbackSeverity.INFO,
            )
        return card.to_dict()

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        return await self.commander.cancel_task(task_id)

    def get_task(self, task_id: str) -> Optional[dict]:
        return self.commander.get_task(task_id)

    def list_active_tasks(self) -> list:
        return self.commander.list_active_tasks()

    def get_stats(self) -> dict:
        return {
            "initialized": self._initialized,
            "commander": self.commander.get_stats(),
            "inspector": self.inspector.get_stats(),
            "executor": self.executor.get_stats(),
        }
