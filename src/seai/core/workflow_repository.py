"""工作流数据访问层 — SQLite 持久化操作"""
import json
import time
import hashlib
from typing import Dict, List, Optional, Any
from sqlite_utils import Database
from loguru import logger


class WorkflowRepository:
    """工作流 SQLite 数据访问层，从 EnhancedWorkflowEngine 分离"""

    def __init__(self, db_path: str):
        self.db = Database(str(db_path))
        self.cache: Dict[str, list] = {}
        self._init_db()
        self._load_cache_from_db()

    def _init_db(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS workflow_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT UNIQUE,
            goal TEXT,
            plan TEXT,
            current_step INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            results TEXT,
            checkpoints TEXT,
            created_at REAL,
            updated_at REAL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS workflow_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            task_id TEXT,
            step_index INTEGER,
            tool_name TEXT,
            attempt INTEGER,
            status TEXT,
            output_preview TEXT,
            error TEXT,
            timestamp REAL
        )""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS workflow_templates (
            name TEXT PRIMARY KEY,
            description TEXT,
            steps TEXT,
            category TEXT,
            version TEXT
        )""")

    def _load_cache_from_db(self):
        rows = self.db.query(
            "SELECT goal, plan FROM workflow_runs WHERE status='success' GROUP BY goal ORDER BY updated_at DESC"
        )
        for row in rows:
            try:
                self.cache[hashlib.md5(row["goal"].encode()).hexdigest()] = json.loads(row["plan"])
            except Exception:
                pass

    @staticmethod
    def cache_key(goal: str) -> str:
        return hashlib.md5(goal.encode()).hexdigest()

    def get_cached_plan(self, goal: str) -> Optional[List[dict]]:
        key = self.cache_key(goal)
        if key in self.cache:
            return self.cache[key]
        return None

    def set_cached_plan(self, goal: str, plan: List[dict]):
        self.cache[self.cache_key(goal)] = plan

    def load_plan_from_db(self, goal: str) -> Optional[List[dict]]:
        rows = list(self.db.query(
            "SELECT plan FROM workflow_runs WHERE goal=? AND status='success' ORDER BY updated_at DESC LIMIT 1",
            [goal]
        ))
        if rows:
            try:
                plan = json.loads(rows[0]["plan"])
                self.cache[self.cache_key(goal)] = plan
                return plan
            except Exception:
                pass
        return None

    # ── workflow_runs CRUD ──────────────────────────

    def insert_run(self, task_id: str, goal: str, plan: str, status: str):
        self.db["workflow_runs"].insert({
            "task_id": task_id,
            "goal": goal,
            "plan": plan,
            "status": status,
            "created_at": time.time(),
            "updated_at": time.time(),
        })

    def update_run_status(self, task_id: str, status: str, current_step: int = None,
                          results: str = None):
        update = {"status": status, "updated_at": time.time()}
        if current_step is not None:
            update["current_step"] = current_step
        if results is not None:
            update["results"] = results
        self.db["workflow_runs"].update(task_id, update, pk="task_id")

    def update_run_progress(self, task_id: str, current_step: int):
        self.db.execute(
            "UPDATE workflow_runs SET current_step=?, updated_at=? WHERE task_id=?",
            [current_step, time.time(), task_id]
        )

    def update_run_checkpoint(self, task_id: str, checkpoints: str):
        self.db.execute(
            "UPDATE workflow_runs SET checkpoints=? WHERE task_id=?",
            [checkpoints, task_id]
        )

    def update_run_full(self, task_id: str, status: str, plan: str,
                        current_step: int):
        self.db.execute(
            "UPDATE workflow_runs SET status=?, plan=?, current_step=?, updated_at=? WHERE task_id=?",
            [status, plan, current_step, time.time(), task_id]
        )

    def get_run(self, task_id: str) -> Optional[dict]:
        return self.db["workflow_runs"].find_one(task_id=task_id)

    def list_runs(self, status: str = None, limit: int = 20) -> List[dict]:
        if status:
            rows = self.db.query(
                "SELECT task_id, goal, status, current_step, created_at, updated_at FROM workflow_runs WHERE status=? ORDER BY updated_at DESC LIMIT ?",
                [status, limit]
            )
        else:
            rows = self.db.query(
                "SELECT task_id, goal, status, current_step, created_at, updated_at FROM workflow_runs ORDER BY updated_at DESC LIMIT ?",
                [limit]
            )
        return [dict(r) for r in rows]

    # ── workflow_events ─────────────────────────────

    def insert_event(self, task_id: str, step_index: int, tool_name: str,
                     attempt: int, status: str, error: str):
        self.db["workflow_events"].insert({
            "task_id": task_id,
            "step_index": step_index,
            "tool_name": tool_name,
            "attempt": attempt,
            "status": status,
            "error": error,
            "timestamp": time.time()
        })

    def get_events(self, task_id: str) -> List[dict]:
        return list(self.db.query(
            "SELECT * FROM workflow_events WHERE task_id=? ORDER BY timestamp",
            [task_id]
        ))

    # ── workflow_templates ──────────────────────────

    def upsert_template(self, name: str, description: str, steps: str,
                        category: str, version: str):
        self.db["workflow_templates"].upsert({
            "name": name,
            "description": description,
            "steps": steps,
            "category": category,
            "version": version
        }, pk="name")

    # ── stats ───────────────────────────────────────

    def get_stats(self, templates_count: int) -> dict:
        total = self.db.query("SELECT COUNT(*) as c FROM workflow_runs")[0]["c"]
        success = self.db.query("SELECT COUNT(*) as c FROM workflow_runs WHERE status='success'")[0]["c"]
        failed = self.db.query("SELECT COUNT(*) as c FROM workflow_runs WHERE status='failed'")[0]["c"]
        return {
            "total_runs": total,
            "success_count": success,
            "failed_count": failed,
            "success_rate": round(success / total * 100, 1) if total > 0 else 0,
            "cached_plans": len(self.cache),
            "templates": templates_count,
        }
