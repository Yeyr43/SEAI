"""
SEAT Inspector Agent — 全流程状态监控
职责：心跳分析、中间产物审查、冲突检测、最终交付判定、进化提案
"""
import time
import asyncio
from typing import Dict, Optional
from loguru import logger

from .seat_task import (
    TaskCard, TaskStatus, AgentRole, AgentHeartbeat, InspectorReport,
    EVT_AGENT_STATUS, EVT_AGENT_RESULT, EVT_AGENT_REQUEST_REVIEW,
    EVT_INSPECTOR_REPORT, EVT_INSPECTOR_RESOLUTION, EVT_INSPECTOR_EVOLVE_PROPOSAL,
    EVT_COMMANDER_DISPATCH, EVT_COMMANDER_CANCEL,
)
from ..event_bus import AsyncEventBus, Event, EventPriority


class InspectorAgent:
    """Inspector — 全流程状态监控 + 审查 + 冲突检测"""

    HEARTBEAT_TIMEOUT = 120.0
    PROGRESS_STALL_THRESHOLD = 60.0

    def __init__(self, event_bus: AsyncEventBus, llm_provider=None):
        self._event_bus = event_bus
        self._llm = llm_provider
        self._agent_id = f"inspector_{id(self):x}"

        self._heartbeats: Dict[str, AgentHeartbeat] = {}
        self._task_artifacts: Dict[str, list] = {}
        self._task_states: Dict[str, TaskStatus] = {}
        self._pending_reviews: Dict[str, list] = {}
        self._monitor_task: Optional[asyncio.Task] = None

    async def start(self):
        self._event_bus.subscribe(EVT_AGENT_STATUS, self._on_heartbeat)
        self._event_bus.subscribe(EVT_AGENT_RESULT, self._on_result)
        self._event_bus.subscribe(EVT_AGENT_REQUEST_REVIEW, self._on_review_request)
        self._event_bus.subscribe(EVT_COMMANDER_DISPATCH, self._on_task_start)
        self._event_bus.subscribe(EVT_COMMANDER_CANCEL, self._on_task_cancel)
        self._monitor_task = asyncio.create_task(self._heartbeat_monitor_loop())
        logger.info("[SEAT] Inspector 已启动")

    async def stop(self):
        if self._monitor_task and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("[SEAT] Inspector 已停止")

    async def _on_task_start(self, event: Event):
        task_id = event.data.get("task_id", "")
        self._task_states[task_id] = TaskStatus.RUNNING
        self._task_artifacts[task_id] = []

    async def _on_task_cancel(self, event: Event):
        task_id = event.data.get("task_id", "")
        self._task_states.pop(task_id, None)
        self._heartbeats.pop(task_id, None)

    async def _on_heartbeat(self, event: Event):
        """接收 Agent 心跳"""
        data = event.data
        hb = AgentHeartbeat(
            agent_id=data.get("agent_id", ""),
            role=AgentRole(data.get("role", "executor")),
            task_id=data.get("task_id", ""),
            status=data.get("status", "running"),
            elapsed_seconds=data.get("elapsed_seconds", 0),
            progress_note=data.get("progress_note", ""),
            timestamp=data.get("timestamp", time.time()),
        )
        self._heartbeats[hb.task_id] = hb

    async def _on_result(self, event: Event):
        """接收 Agent 子任务结果"""
        data = event.data
        task_id = data.get("task_id", "")
        artifact = {
            "agent_id": data.get("agent_id", ""),
            "summary": data.get("summary", "")[:300],
            "timestamp": time.time(),
        }
        if task_id not in self._task_artifacts:
            self._task_artifacts[task_id] = []
        self._task_artifacts[task_id].append(artifact)

    async def _on_review_request(self, event: Event):
        """接收审查请求 — 执行审查"""
        data = event.data
        task_id = data.get("task_id", "")
        if task_id not in self._pending_reviews:
            self._pending_reviews[task_id] = []
        self._pending_reviews[task_id].append(data)

        report = await self._review(task_id, data)
        await self._emit_report(report)

    async def _review(self, task_id: str, data: dict) -> InspectorReport:
        """审查 Agent 提交的交付物（启发式 + LLM 双重审查）"""
        agent_id = data.get("agent_id", "")
        result = data.get("result", "")
        artifacts = self._task_artifacts.get(task_id, [])

        issues = []
        suggestions = []

        # — 启发式快速审查 —
        if not result or len(str(result)) < 5:
            issues.append("交付物为空或过短")

        if result and any(w in str(result).lower() for w in ["错误", "失败", "无法", "error", "failed"]):
            issues.append("交付物包含错误指示词")

        error_count = sum(1 for a in artifacts
                         if any(w in str(a.get("summary", "")).lower()
                                for w in ["error", "failed", "exception"]))

        if error_count >= 2:
            issues.append(f"执行过程中发现 {error_count} 个错误")

        if len(artifacts) > 5 and error_count == 0:
            suggestions.append("考虑合并相似中间结果以减少 Token 消耗")

        # — LLM 深度审查 —
        llm_issues, llm_suggestions = await self._llm_review(result)
        issues.extend(llm_issues)
        suggestions.extend(llm_suggestions)

        approved = len(issues) == 0
        summary = f"Agent {agent_id} 交付" + ("通过" if approved else "未通过")

        return InspectorReport(
            task_id=task_id,
            approved=approved,
            summary=summary,
            issues=issues,
            suggestions=suggestions,
        )

    async def _llm_review(self, result: str) -> tuple:
        """使用 LLM 对交付物进行深度审查"""
        if not self._llm or not result:
            return [], []

        prompt = f"""你是一个严格的质量审查员。审查以下交付物，找出问题。

交付物内容：
{str(result)[:1500]}

请指出：
1. 是否有逻辑错误、遗漏、格式问题？
2. 是否有改进建议？

以 JSON 格式输出：
{{"issues": ["问题1", "问题2"], "suggestions": ["建议1"]}}
如果没有问题，返回 {{"issues": [], "suggestions": []}}
只输出 JSON。"""
        try:
            response = await self._llm.chat([{"role": "user", "content": prompt}])
            text = response if isinstance(response, str) else response.get("content", "")
            import json
            data = json.loads(text)
            return data.get("issues", []), data.get("suggestions", [])
        except Exception:
            return [], []

    async def _emit_report(self, report: InspectorReport):
        """发出审查报告"""
        event = Event(
            event_type=EVT_INSPECTOR_REPORT,
            source=self._agent_id,
            data={
                "task_id": report.task_id,
                "approved": report.approved,
                "summary": report.summary,
                "issues": report.issues,
                "suggestions": report.suggestions,
            },
            priority=EventPriority.HIGH if not report.approved else EventPriority.NORMAL,
        )
        await self._event_bus.publish(event)

    async def _heartbeat_monitor_loop(self):
        """心跳监控循环 — 检测僵死/超时/异常"""
        while True:
            try:
                now = time.time()
                for task_id, hb in list(self._heartbeats.items()):
                    elapsed = now - hb.timestamp
                    if elapsed > self.HEARTBEAT_TIMEOUT:
                        logger.warning(f"[SEAT] 任务 {task_id} 心跳超时 ({elapsed:.0f}s)")
                        self._task_states[task_id] = TaskStatus.BLOCKED
                        self._heartbeats.pop(task_id, None)
                        await self._emit_resolution(task_id, "blocked", f"心跳超时 {elapsed:.0f}s")

                await asyncio.sleep(15)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[SEAT] 心跳监控异常: {e}")
                await asyncio.sleep(30)

    async def _emit_resolution(self, task_id: str, status: str, reason: str = ""):
        """发出状态变更决议"""
        event = Event(
            event_type=EVT_INSPECTOR_RESOLUTION,
            source=self._agent_id,
            data={"task_id": task_id, "status": status, "reason": reason},
        )
        await self._event_bus.publish(event)

    def get_stats(self) -> dict:
        return {
            "active_tasks": len(self._task_states),
            "pending_reviews": len(self._pending_reviews),
            "heartbeats_active": len(self._heartbeats),
        }
