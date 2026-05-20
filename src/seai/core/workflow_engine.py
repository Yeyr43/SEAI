# ══════════════════════════════════════════════════
# core/workflow_engine.py - 增强工作流引擎 v2.0
# ══════════════════════════════════════════════════
import ast
import asyncio, json, time, hashlib
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger
from .workflow_repository import WorkflowRepository


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    WAITING_HUMAN = "waiting_human"


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCESS = "success"
    FAILED = "failed"
    ABORTED = "aborted"


@dataclass
class WorkflowStep:
    tool: str
    params: dict = field(default_factory=dict)
    depends_on: List[int] = field(default_factory=list)
    condition: Optional[str] = None
    on_failure: str = "stop"
    max_retries: int = 3
    human_confirm: bool = False
    status: StepStatus = StepStatus.PENDING
    output: Any = None
    error: Optional[str] = None
    retry_count: int = 0


@dataclass
class WorkflowTemplate:
    name: str
    description: str
    steps: List[dict]
    category: str = "general"
    version: str = "1.0"


class EnhancedWorkflowEngine:
    def __init__(self, agent):
        self.agent = agent
        self.repo = WorkflowRepository(str(agent.data_dir / "workflow.db"))
        self._templates: Dict[str, WorkflowTemplate] = {}
        self._register_builtin_templates()
        self._progress_callbacks: List[Callable] = []
        self._checkpoints: Dict[str, dict] = {}

    def _register_builtin_templates(self):
        self._templates["code_review"] = WorkflowTemplate(
            name="code_review",
            description="代码审查工作流",
            category="development",
            steps=[
                {"tool": "read_file", "params": {"path": "{{file_path}}"}},
                {"tool": "skill_code_analysis", "params": {"code": "{{prev_output}}"}},
                {"tool": "write_file", "params": {"path": "{{review_output_path}}", "content": "{{prev_output}}"}}
            ]
        )
        self._templates["data_pipeline"] = WorkflowTemplate(
            name="data_pipeline",
            description="数据处理流水线",
            category="data",
            steps=[
                {"tool": "read_file", "params": {"path": "{{input_path}}"}},
                {"tool": "skill_data_transform", "params": {"data": "{{prev_output}}", "format": "{{output_format}}"}},
                {"tool": "write_file", "params": {"path": "{{output_path}}", "content": "{{prev_output}}"}}
            ]
        )

    def register_template(self, template: WorkflowTemplate):
        self._templates[template.name] = template
        self.repo.upsert_template(
            template.name, template.description,
            json.dumps(template.steps, ensure_ascii=False),
            template.category, template.version
        )

    def get_template(self, name: str) -> Optional[WorkflowTemplate]:
        return self._templates.get(name)

    def on_progress(self, callback: Callable):
        self._progress_callbacks.append(callback)

    def _notify_progress(self, task_id: str, step_index: int, total_steps: int, status: str):
        for cb in self._progress_callbacks:
            try:
                cb(task_id, step_index, total_steps, status)
            except Exception:
                pass

    async def plan(self, goal: str, template_name: str = None) -> List[dict]:
        if template_name and template_name in self._templates:
            return self._templates[template_name].steps

        cached = self.repo.get_cached_plan(goal)
        if cached:
            return cached

        db_plan = self.repo.load_plan_from_db(goal)
        if db_plan:
            return db_plan

        prompt = f"""为以下目标生成步骤列表，每步包含 tool 和 params。
支持 depends_on（依赖步骤索引列表）、condition（条件表达式）、on_failure（stop/continue/retry）、human_confirm（bool）。

目标：{goal}
格式：json 数组"""
        resp = await self.agent.llm_manager.chat([{"role": "user", "content": prompt}])
        try:
            plan = json.loads(resp)
            self.repo.set_cached_plan(goal, plan)
            return plan
        except Exception:
            return []

    async def execute(self, goal: str, template_name: str = None, variables: dict = None) -> dict:
        task_id = f"wf_{int(time.time())}_{hashlib.md5(goal.encode()).hexdigest()[:6]}"
        plan = await self.plan(goal, template_name)

        if not plan:
            return {"status": "failed", "error": "无法生成计划"}

        if variables:
            plan = self._apply_variables(plan, variables)

        steps = [WorkflowStep(**s) if isinstance(s, dict) else s for s in plan]

        self.repo.insert_run(task_id, goal, json.dumps(plan, ensure_ascii=False),
                             WorkflowStatus.RUNNING.value)

        results = await self._execute_steps(task_id, steps)
        return results

    def _apply_variables(self, plan: List[dict], variables: dict) -> List[dict]:
        plan_str = json.dumps(plan, ensure_ascii=False)
        for key, value in variables.items():
            plan_str = plan_str.replace(f"{{{{{key}}}}}", str(value))
        return json.loads(plan_str)

    async def _execute_steps(self, task_id: str, steps: List[WorkflowStep]) -> dict:
        total = len(steps)
        results = []
        step_outputs = {}

        for i, step in enumerate(steps):
            if step.status == StepStatus.SKIPPED:
                results.append({"step": i, "status": "skipped"})
                continue

            deps_met = all(
                d < len(results) and results[d].get("status") == "success"
                for d in step.depends_on
            )
            if not deps_met:
                step.status = StepStatus.SKIPPED
                results.append({"step": i, "status": "skipped", "reason": "依赖未满足"})
                continue

            if step.condition:
                condition_met = self._evaluate_condition(step.condition, step_outputs)
                if not condition_met:
                    step.status = StepStatus.SKIPPED
                    results.append({"step": i, "status": "skipped", "reason": "条件不满足"})
                    continue

            if step.human_confirm:
                self._save_checkpoint(task_id, i, steps, results)
                self.repo.update_run_status(task_id, WorkflowStatus.PAUSED.value, current_step=i)
                return {
                    "status": "paused",
                    "task_id": task_id,
                    "message": f"步骤 {i} 需要人工确认",
                    "step": {"tool": step.tool, "params": step.params}
                }

            step.status = StepStatus.RUNNING
            self._notify_progress(task_id, i, total, "running")
            self.repo.update_run_progress(task_id, i)
            success = False
            for retry in range(step.max_retries):
                try:
                    if step.tool.startswith("skill_"):
                        result = await self.agent.skill_system.execute_skill(
                            step.tool[6:], step.params, security=self.agent.security
                        )
                    else:
                        result = await self.agent.tool_executor.execute_tool(step.tool, step.params)

                    step.output = str(result)
                    step.status = StepStatus.SUCCESS
                    step_outputs[i] = str(result)
                    success = True
                    break
                except Exception as e:
                    error_msg = str(e)
                    step.retry_count = retry + 1
                    self.repo.insert_event(task_id, i, step.tool, retry + 1, "failed", error_msg)
                    if retry < step.max_retries - 1:
                        await asyncio.sleep(2 ** retry)

            if not success:
                step.status = StepStatus.FAILED
                step.error = error_msg if 'error_msg' in dir() else "未知错误"

                if step.on_failure == "stop":
                    self.repo.update_run_status(
                        task_id, WorkflowStatus.FAILED.value,
                        results=json.dumps(results, ensure_ascii=False)
                    )
                    return {"status": "failed", "task_id": task_id, "results": results, "failed_at_step": i}

            results.append({
                "step": i,
                "tool": step.tool,
                "status": step.status.value,
                "output": step.output,
                "error": step.error
            })

        final_status = WorkflowStatus.SUCCESS.value if all(
            r.get("status") in ("success", "skipped") for r in results
        ) else WorkflowStatus.FAILED.value

        self.repo.update_run_status(
            task_id, final_status,
            results=json.dumps(results, ensure_ascii=False)
        )
        return {"status": final_status, "task_id": task_id, "results": results}

    def _evaluate_condition(self, condition: str, outputs: dict) -> bool:
        try:
            tree = ast.parse(condition, mode="eval")

            SAFE_NODES = {
                ast.Expression, ast.BoolOp, ast.Compare, ast.Name, ast.Load,
                ast.Constant, ast.And, ast.Or, ast.Not, ast.UnaryOp, ast.USub,
                ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Is,
                ast.IsNot, ast.In, ast.NotIn,
                ast.Subscript, ast.Index, ast.Slice,
                ast.List, ast.Tuple, ast.Dict, ast.keyword,
                ast.Call, ast.Attribute,
            }
            if any(type(n) not in SAFE_NODES for n in ast.walk(tree)):
                logger.warning(f"条件含不允许的 AST 节点: {condition}")
                return True

            safe_builtins = {
                "True": True, "False": False, "None": None,
                "len": len, "int": int, "float": float,
                "str": str, "bool": bool, "list": list, "dict": dict,
                "isinstance": isinstance, "type": type,
                "min": min, "max": max, "abs": abs, "any": any, "all": all,
            }
            return bool(eval(condition, {"__builtins__": safe_builtins}, {"outputs": outputs}))
        except Exception as e:
            logger.warning(f"条件评估异常: {e}")
            return True

    def _save_checkpoint(self, task_id: str, step_index: int, steps: list, results: list):
        self._checkpoints[task_id] = {
            "step_index": step_index,
            "steps": [{"tool": s.tool, "params": s.params, "status": s.status.value} for s in steps],
            "results": results,
            "timestamp": time.time()
        }
        self.repo.update_run_checkpoint(
            task_id, json.dumps(self._checkpoints[task_id], ensure_ascii=False)
        )

    async def resume(self, task_id: str, action: str = "retry", step_index: int = None, human_input: str = None) -> dict:
        row = self.repo.get_run(task_id)
        if not row:
            return {"status": "not_found"}

        if row["status"] not in (WorkflowStatus.PAUSED.value, WorkflowStatus.FAILED.value):
            return {"status": "error", "message": f"任务状态为 {row['status']}，无法恢复"}

        plan_data = json.loads(row["plan"])
        current_step = step_index if step_index is not None else row["current_step"]

        if action == "skip":
            plan_data[current_step]["status"] = "skipped"
            current_step += 1
        elif action == "retry":
            plan_data[current_step]["status"] = "pending"
        elif action == "abort":
            self.repo.update_run_status(task_id, WorkflowStatus.ABORTED.value)
            return {"status": "aborted"}
        elif action == "rollback":
            checkpoint = self._checkpoints.get(task_id)
            if checkpoint:
                current_step = checkpoint["step_index"]
                plan_data = checkpoint["steps"]

        self.repo.update_run_full(
            task_id, WorkflowStatus.RUNNING.value,
            json.dumps(plan_data, ensure_ascii=False), current_step
        )

        steps = [WorkflowStep(**s) if isinstance(s, dict) else s for s in plan_data]
        return await self._execute_remaining(task_id, steps, current_step)

    async def _execute_remaining(self, task_id: str, steps: List[WorkflowStep], start_from: int) -> dict:
        self.repo.get_events(task_id)  # no-op for now, used by external monitoring
        results = []

        for i in range(start_from, len(steps)):
            step = steps[i]
            step.status = StepStatus.RUNNING
            self._notify_progress(task_id, i, len(steps), "running")

            try:
                if step.tool.startswith("skill_"):
                    result = await self.agent.skill_system.execute_skill(
                        step.tool[6:], step.params, security=self.agent.security
                    )
                else:
                    result = await self.agent.tool_executor.execute_tool(step.tool, step.params)
                step.output = str(result)
                step.status = StepStatus.SUCCESS
            except Exception as e:
                step.status = StepStatus.FAILED
                step.error = str(e)

            results.append({
                "step": i,
                "tool": step.tool,
                "status": step.status.value,
                "output": step.output,
                "error": step.error
            })

        self.repo.update_run_status(
            task_id, WorkflowStatus.SUCCESS.value,
            results=json.dumps(results, ensure_ascii=False)
        )
        return {"status": "success", "task_id": task_id, "results": results}

    async def execute_parallel(self, goal: str, parallel_groups: List[List[dict]]) -> dict:
        task_id = f"wfp_{int(time.time())}_{hashlib.md5(goal.encode()).hexdigest()[:6]}"
        all_results = []

        for group_idx, group in enumerate(parallel_groups):
            tasks = []
            for step in group:
                tasks.append(self._execute_single_step(step.get("tool", ""), step.get("params", {})))

            group_results = await asyncio.gather(*tasks, return_exceptions=True)
            for j, result in enumerate(group_results):
                if isinstance(result, Exception):
                    all_results.append({"group": group_idx, "step": j, "status": "failed", "error": str(result)})
                else:
                    all_results.append({"group": group_idx, "step": j, "status": "success", "output": str(result)})

        return {"status": "success", "task_id": task_id, "results": all_results}

    async def _execute_single_step(self, tool_name: str, params: dict) -> Any:
        if tool_name.startswith("skill_"):
            return await self.agent.skill_system.execute_skill(
                tool_name[6:], params, security=self.agent.security
            )
        else:
            return await self.agent.tool_executor.execute_tool(tool_name, params)

    def get_run_status(self, task_id: str) -> Optional[dict]:
        row = self.repo.get_run(task_id)
        if not row:
            return None
        return {
            "task_id": row["task_id"],
            "goal": row["goal"],
            "status": row["status"],
            "current_step": row["current_step"],
            "plan": json.loads(row["plan"]) if row["plan"] else [],
            "results": json.loads(row["results"]) if row["results"] else [],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"]
        }

    def list_runs(self, status: str = None, limit: int = 20) -> List[dict]:
        return self.repo.list_runs(status, limit)

    def get_stats(self) -> dict:
        return self.repo.get_stats(len(self._templates))
