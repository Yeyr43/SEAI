"""
SEAT Commander Agent — 极简调度器
职责：任务接收、难度评估、派发、取消。
不参与 Agent 间网状通信（仅通过指令信道下发）。
"""
import time
import asyncio
from typing import Dict, Optional, Callable
from loguru import logger

from .seat_task import (
    TaskCard, TaskStatus, AgentRole, DifficultyLevel,
    EVT_COMMANDER_DISPATCH, EVT_COMMANDER_CANCEL,
    EVT_INSPECTOR_RESOLUTION, EVT_INSPECTOR_REPORT,
)
from ..event_bus import AsyncEventBus, Event, EventPriority


class CommanderAgent:
    """Commander — 极简调度器"""

    def __init__(self, event_bus: AsyncEventBus, llm_provider=None, complexity_estimator=None):
        self._event_bus = event_bus
        self._llm = llm_provider
        self._complexity_estimator = complexity_estimator
        self._active_tasks: Dict[str, TaskCard] = {}
        self._task_history: Dict[str, TaskCard] = {}
        self._dispatch_callback: Optional[Callable] = None
        self._agent_id = f"commander_{id(self):x}"

    async def start(self):
        """订阅事件"""
        self._event_bus.subscribe(EVT_INSPECTOR_REPORT, self._on_inspector_report)
        self._event_bus.subscribe(EVT_INSPECTOR_RESOLUTION, self._on_resolution)
        logger.info("[SEAT] Commander 已启动")

    async def stop(self):
        for task_id in list(self._active_tasks.keys()):
            await self.cancel_task(task_id)
        logger.info("[SEAT] Commander 已停止")

    async def submit_task(self, goal: str, context: dict = None) -> TaskCard:
        """接收新任务 → 评估难度 → 派发"""
        difficulty = await self._assess_difficulty(goal)

        card = TaskCard(
            goal=goal,
            difficulty=difficulty,
            context=context or {},
            status=TaskStatus.PENDING,
        )
        self._active_tasks[card.task_id] = card
        self._task_history[card.task_id] = card

        await self._dispatch(card)
        return card

    async def _assess_difficulty(self, goal: str) -> DifficultyLevel:
        """评估任务难度"""
        if self._complexity_estimator:
            try:
                score = self._complexity_estimator.estimate(goal)
                if score >= 0.8:
                    return DifficultyLevel.COMPLEX
                elif score >= 0.6:
                    return DifficultyLevel.HARD
                elif score >= 0.4:
                    return DifficultyLevel.MEDIUM
                elif score >= 0.2:
                    return DifficultyLevel.EASY
                return DifficultyLevel.TRIVIAL
            except Exception:
                pass

        if len(goal) > 500:
            return DifficultyLevel.HARD
        elif len(goal) > 200:
            return DifficultyLevel.MEDIUM
        return DifficultyLevel.EASY

    async def _dispatch(self, card: TaskCard):
        """派发任务卡到 EventBus"""
        card.status = TaskStatus.RUNNING
        card.updated_at = time.time()

        event = Event(
            event_type=EVT_COMMANDER_DISPATCH,
            source=self._agent_id,
            data=card.to_dict(),
            priority=EventPriority.HIGH,
        )
        await self._event_bus.publish(event)
        logger.info(f"[SEAT] Commander 派发任务 {card.task_id}: {card.goal[:60]} ({card.difficulty.value})")

        if self._dispatch_callback:
            try:
                self._dispatch_callback(card)
            except Exception:
                pass

    async def cancel_task(self, task_id: str) -> bool:
        """取消任务"""
        card = self._active_tasks.get(task_id)
        if not card:
            return False

        card.status = TaskStatus.CANCELLED
        card.updated_at = time.time()
        self._active_tasks.pop(task_id, None)

        event = Event(
            event_type=EVT_COMMANDER_CANCEL,
            source=self._agent_id,
            data={"task_id": task_id},
            priority=EventPriority.HIGH,
        )
        await self._event_bus.publish(event)
        logger.info(f"[SEAT] Commander 取消任务 {task_id}")
        return True

    async def _on_inspector_report(self, event: Event):
        """处理 Inspector 审查报告"""
        data = event.data
        task_id = data.get("task_id", "")
        card = self._active_tasks.get(task_id)
        if not card:
            return

        if data.get("approved"):
            card.status = TaskStatus.COMPLETED
            card.completed_at = time.time()
            card.result = data.get("summary")
            self._active_tasks.pop(task_id, None)
            logger.info(f"[SEAT] 任务 {task_id} 已完成")
        else:
            issues = data.get("issues", [])
            if any("冲突" in i for i in issues):
                card.status = TaskStatus.DEADLOCK
                await self._arbitrate(card, data)
            elif any("超出范围" in i for i in issues):
                card.status = TaskStatus.OUT_OF_SCOPE
                await self._re_dispatch(card, data)

    async def _arbitrate(self, card: TaskCard, report: dict):
        """死锁仲裁 — 重新派发或标记失败"""
        logger.warning(f"[SEAT] 任务 {card.task_id} 死锁，进行仲裁")
        card.status = TaskStatus.RUNNING
        event = Event(
            event_type=EVT_COMMANDER_ARBITRATE,
            source=self._agent_id,
            data={"task_id": card.task_id, "goal": card.goal, "issues": report.get("issues", [])},
        )
        await self._event_bus.publish(event)

    async def _re_dispatch(self, card: TaskCard, report: dict):
        """超出范围时修正后重新派发"""
        suggestions = report.get("suggestions", [])
        if suggestions:
            card.context["correction"] = suggestions[0]
        card.status = TaskStatus.RUNNING
        await self._dispatch(card)

    async def _on_resolution(self, event: Event):
        """处理任务状态变更"""
        data = event.data
        task_id = data.get("task_id", "")
        new_status = data.get("status", "")
        card = self._active_tasks.get(task_id)
        if not card:
            return
        if new_status == "completed":
            card.status = TaskStatus.COMPLETED
            card.completed_at = time.time()
            card.result = data.get("result")
            self._active_tasks.pop(task_id, None)

    def get_task(self, task_id: str) -> Optional[dict]:
        card = self._task_history.get(task_id)
        return card.to_dict() if card else None

    def list_active_tasks(self) -> list:
        return [c.to_dict() for c in self._active_tasks.values()]

    def on_dispatch(self, callback: Callable):
        self._dispatch_callback = callback

    def get_stats(self) -> dict:
        return {
            "active_tasks": len(self._active_tasks),
            "total_tasks": len(self._task_history),
        }
