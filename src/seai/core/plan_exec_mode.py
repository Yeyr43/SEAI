"""
SEAI Plan/Execute 双阶段模式 — 复杂任务的规划-执行分流

PlanMode：  仅允许只读工具（read_file, grep, glob, web_search），生成 ExecutionPlan
ExecuteMode：允许所有工具，按步骤执行并在检查点自动验证
"""
import json
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from loguru import logger


class PlanStatus(str, Enum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PlanStep:
    """执行计划步骤"""
    step_id: int
    description: str
    expected_output: str
    tool_hint: str = ""  # 建议使用的工具
    checkpoint: bool = False  # 是否在此步骤后检查
    completed: bool = False
    result_summary: str = ""

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id, "description": self.description,
            "expected_output": self.expected_output, "tool_hint": self.tool_hint,
            "checkpoint": self.checkpoint, "completed": self.completed,
            "result_summary": self.result_summary,
        }


@dataclass
class ExecutionPlan:
    """完整的执行计划"""
    plan_id: str = ""
    task_description: str = ""
    steps: List[PlanStep] = field(default_factory=list)
    status: PlanStatus = PlanStatus.DRAFT
    created_at: float = field(default_factory=time.time)
    approved_by: str = ""
    difficulty_level: int = 1  # 1-4

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id, "task_description": self.task_description,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status.value, "created_at": self.created_at,
            "approved_by": self.approved_by, "difficulty_level": self.difficulty_level,
        }

    def progress(self) -> tuple:
        total = len(self.steps)
        completed = sum(1 for s in self.steps if s.completed)
        return completed, total

    def next_step(self) -> Optional[PlanStep]:
        for step in self.steps:
            if not step.completed:
                return step
        return None


class PlanExecMode:
    """Plan/Execute 模式管理器"""

    # Plan 模式下仅允许的只读工具
    PLAN_READONLY_TOOLS = {"read_file", "list_files", "grep", "glob", "web_search",
                           "fetch_url", "echo", "calculator", "get_image_info"}

    def __init__(self, llm_provider=None, permission_manager=None):
        self.llm_provider = llm_provider
        self.permission_manager = permission_manager
        self._current_plan: Optional[ExecutionPlan] = None
        self._plan_history: List[ExecutionPlan] = []

    @property
    def current_plan(self) -> Optional[ExecutionPlan]:
        return self._current_plan

    @property
    def is_planning(self) -> bool:
        return self._current_plan is not None and self._current_plan.status == PlanStatus.DRAFT

    @property
    def is_executing(self) -> bool:
        return self._current_plan is not None and self._current_plan.status == PlanStatus.EXECUTING

    def is_tool_allowed_in_plan(self, tool_name: str) -> bool:
        """检查工具是否在 Plan 模式下被允许"""
        return tool_name in self.PLAN_READONLY_TOOLS

    async def create_plan(self, task_description: str, complexity: int = 2) -> ExecutionPlan:
        """基于任务描述创建执行计划（使用 LLM 或规则分解）"""
        import uuid

        if self.llm_provider and complexity >= 2:
            steps = await self._llm_create_plan(task_description)
        else:
            steps = self._rule_create_plan(task_description)

        plan = ExecutionPlan(
            plan_id=uuid.uuid4().hex[:12],
            task_description=task_description,
            steps=steps,
            status=PlanStatus.DRAFT,
            difficulty_level=complexity,
        )
        self._current_plan = plan
        return plan

    async def _llm_create_plan(self, task_description: str) -> List[PlanStep]:
        try:
            prompt = (
                "请将以下任务分解为可执行的步骤列表。每个步骤包含：序号、描述、预期产出、建议工具。\n"
                "重要步骤标记 checkpoint=true。返回 JSON 数组格式：\n"
                '[{"step_id":1,"description":"步骤描述","expected_output":"预期产出",'
                '"tool_hint":"建议工具","checkpoint":false}]\n\n'
                f"任务: {task_description}"
            )
            response = await self.llm_provider.chat([{"role": "user", "content": prompt}])
            if isinstance(response, str):
                data = json.loads(response)
            else:
                data = response
            if isinstance(data, list):
                return [
                    PlanStep(
                        step_id=s.get("step_id", i + 1),
                        description=s.get("description", ""),
                        expected_output=s.get("expected_output", ""),
                        tool_hint=s.get("tool_hint", ""),
                        checkpoint=s.get("checkpoint", False),
                    )
                    for i, s in enumerate(data)
                ]
        except Exception as e:
            logger.warning(f"LLM 创建计划失败: {e}")

        return self._rule_create_plan(task_description)

    def _rule_create_plan(self, task_description: str) -> List[PlanStep]:
        """基于规则的简单任务分解"""
        steps = []
        task_lower = task_description.lower()

        if any(kw in task_lower for kw in ("搜索", "search", "grep", "find")):
            steps.append(PlanStep(1, "分析搜索范围和目标", "确定搜索路径和模式", "grep"))
            steps.append(PlanStep(2, "执行搜索", "获取匹配结果列表", "grep", checkpoint=True))
            steps.append(PlanStep(3, "整理结果", "格式化搜索结果摘要", ""))

        elif any(kw in task_lower for kw in ("写", "write", "创建", "create", "生成", "generate")):
            steps.append(PlanStep(1, "分析需求和现有代码", "理解上下文", "read_file"))
            steps.append(PlanStep(2, "编写代码", "生成目标代码", "write_file", checkpoint=True))
            steps.append(PlanStep(3, "验证结果", "检查代码正确性", "read_file"))

        elif any(kw in task_lower for kw in ("修复", "fix", "bug", "错误", "debug")):
            steps.append(PlanStep(1, "分析错误信息", "理解错误原因", "read_file"))
            steps.append(PlanStep(2, "定位问题代码", "找到bug位置", "grep", checkpoint=True))
            steps.append(PlanStep(3, "应用修复", "修改代码", "edit"))
            steps.append(PlanStep(4, "验证修复", "确认错误已解决", ""))

        else:
            steps.append(PlanStep(1, "理解任务需求", "明确要完成什么", "read_file"))
            steps.append(PlanStep(2, "执行任务", "完成用户要求的操作", "", checkpoint=True))
            steps.append(PlanStep(3, "汇报结果", "总结执行结果", ""))

        return steps

    def approve_plan(self, approver: str = "user") -> ExecutionPlan:
        """审批通过，进入执行模式"""
        if self._current_plan:
            self._current_plan.status = PlanStatus.APPROVED
            self._current_plan.approved_by = approver
            self._current_plan.status = PlanStatus.EXECUTING
        return self._current_plan

    def mark_step_complete(self, step_id: int, result_summary: str = ""):
        """标记步骤完成"""
        if self._current_plan:
            for step in self._current_plan.steps:
                if step.step_id == step_id:
                    step.completed = True
                    step.result_summary = result_summary
                    break

    def check_progress(self) -> dict:
        """检查执行进度，检测是否偏离计划"""
        if not self._current_plan:
            return {"error": "无活跃计划"}
        completed, total = self._current_plan.progress()
        next_step = self._current_plan.next_step()
        return {
            "plan_id": self._current_plan.plan_id,
            "status": self._current_plan.status.value,
            "progress": f"{completed}/{total}",
            "next_step": next_step.description if next_step else "全部完成",
            "next_checkpoint": next_step.checkpoint if next_step else None,
        }

    def complete_plan(self) -> ExecutionPlan:
        """标记计划完成"""
        if self._current_plan:
            self._current_plan.status = PlanStatus.COMPLETED
            self._plan_history.append(self._current_plan)
            self._current_plan = None
        return self._current_plan

    def get_stats(self) -> dict:
        return {
            "active_plan": self._current_plan is not None,
            "current_status": self._current_plan.status.value if self._current_plan else None,
            "history_count": len(self._plan_history),
        }
