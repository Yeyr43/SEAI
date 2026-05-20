""""""
from .. import net
from ..seat import SEATEngine
from ..circuit_breaker import breaker_manager
from ..config import ConfigManager
from ..config import config_manager
from ..constraint_engine import ConstraintEngine
from ..context_retriever import ContextRetriever
from ..conversation_service import ConversationService
from ..error_handler import SmartErrorHandler
from ..evolution_service import EvolutionService
from ..evolution_tester import EvolutionTester
from ..execution_pipeline import ExecutionPipeline
from ..feedback_loop import FeedbackLoop
from ..interfaces.llm_provider import LLMProvider
from ..interfaces.memory_store import MemoryStore
from ..interfaces.skill_repository import SkillRepository
from ..interfaces.tool_executor import ToolExecutor
from ..lifecycle import AgentLifecycleManager
from ..media_encoder import MediaEncoder
from ..prompt_composer import PromptComposer
from ..reflection_engine import ReflectionEngine
from ..security import SecurityManager
from ..session_manager import SessionManager
from ..sub_agent import AgentPool
from ..sub_agent import ParallelScheduler
from ..sub_agent import ResultMerger
from ..sub_agent import TaskComplexityEstimator
from ..sub_agent import TaskDecomposer
from ..tool_loop import detect_intent
from ..workflow_engine import EnhancedWorkflowEngine
from datetime import datetime
from datetime import timedelta
from loguru import logger
from pathlib import Path
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
import asyncio
import json
import sys
import time

class AgentMixin:
    def __init__(self, config: ConfigManager = None):
        self.config = config or config_manager
        system_config = self.config.get_system_config()
        self.lifecycle_manager = AgentLifecycleManager(self.config)

        self.llm_provider: Optional[LLMProvider] = None
        self.memory_store: Optional[MemoryStore] = None
        self.tool_executor: Optional[ToolExecutor] = None
        self.skill_repository: Optional[SkillRepository] = None

        self.data_dir = system_config.data_dir
        self.workspace = system_config.workspace_dir
        self.schedule_path = self.data_dir / "schedule.json"
        self.scheduled_outputs_dir = self.data_dir / "scheduled_outputs"
        self.scheduled_outputs_dir.mkdir(parents=True, exist_ok=True)

        from ..session_manager import SessionManager
        self.session_manager = SessionManager()
        self.session_manager.set_sessions_dir(self.data_dir / "sessions")
        self.session_manager.set_context_dir(self.data_dir / "session_contexts")

        self.knowledge_graph_manager = None

        self.thinking_enabled = True
        net.enable()
        self.current_session_id = ""
        self.current_locale = "zh-CN"
        self.current_role: Optional[str] = None

        self._tool_cache: Dict[str, Any] = {}
        self._max_tool_cache = 200
        self._last_tool_call_time: Dict[str, float] = {}
        self._prompt_engine = None
        self._self_check_context = ""
        self._token_log: List[Dict] = []
        self._token_log_file_path: Optional[Path] = None

        # 从 agent.py 提取的协作文档
        self._context_retriever: Optional[ContextRetriever] = None
        self._prompt_composer: Optional[PromptComposer] = None
        self._media_encoder: Optional[MediaEncoder] = None
        self._skill_first_use: Dict[str, bool] = {}
        self._log_tool_feedback_cache: List[Dict] = []
        self._active_requests: List[asyncio.Task] = []

        self._llm_breaker = breaker_manager.get_or_create("llm_call", failure_threshold=3, cooldown_seconds=30.0)
        self._tool_breaker = breaker_manager.get_or_create("tool_exec", failure_threshold=5, cooldown_seconds=60.0)
        self._error_handler: Optional[SmartErrorHandler] = None
        self._evolution_tester: Optional[EvolutionTester] = None

        self._multi_agent_config = {
            "enabled": True,
            "parallel_execution": True,
            "max_sub_agents": 3,
            "complexity_threshold": 0.5,
            "token_budget_per_sub_agent": 3000,
        }
        self._complexity_estimator: Optional[TaskComplexityEstimator] = None
        self._agent_pool: Optional[AgentPool] = None
        self._task_decomposer: Optional[TaskDecomposer] = None
        self._parallel_scheduler: Optional[ParallelScheduler] = None
        self._result_merger: Optional[ResultMerger] = None
        self._constraint_engine: Optional[ConstraintEngine] = None
        self._feedback_loop: Optional[FeedbackLoop] = None
        self._conversation_service: Optional[ConversationService] = None
        self._evolution_service: Optional[EvolutionService] = None
        self._pipeline: Optional[ExecutionPipeline] = None
        self._seat_engine: Optional['SEATEngine'] = None

    @property
    def llm_manager(self):
        return self.llm_provider

    @property
    def skill_system(self):
        return self.skill_repository

    @property
    def security(self):
        if not hasattr(self, '_security'):
            from ..security import SecurityManager
            system_config = self.config.get_system_config()
            self._security = SecurityManager(
                workspace=system_config.workspace_dir,
                skills_dir=system_config.data_dir / "skills"
            )
        return self._security

    @property
    def workflow_engine(self):
        if not hasattr(self, '_workflow_engine'):
            from ..workflow_engine import EnhancedWorkflowEngine
            self._workflow_engine = EnhancedWorkflowEngine(agent=self)
        return self._workflow_engine

    def _detect_intent(self, query: str) -> str:
        if hasattr(self, '_reflection_engine') and self._reflection_engine is not None:
            return self._reflection_engine.detect_intent(query)
        from ..tool_loop import detect_intent
        return detect_intent(query)

    @staticmethod

    def _extract_user_interests(query: str) -> List[str]:
        """从用户查询中提取兴趣偏好（委托给 ReflectionEngine）"""
        from ..reflection_engine import ReflectionEngine
        # 使用静态方法模拟（ReflectionEngine.extract_user_interests 是实例方法）
        tmp = ReflectionEngine()
        return tmp.extract_user_interests(query)

    def _detect_memory_types(self, query: str) -> List[str]:
        if self._context_retriever:
            return self._context_retriever.detect_memory_types(query)
        return None

    def _get_time_relevant_memories(self, query: str) -> str:
        if self._context_retriever:
            return self._context_retriever.get_time_relevant_memories(query)
        return ""

    def _estimate_tokens(self, messages: List[Dict]) -> int:
        """估算消息 token 数（委托给 LLM 管理器的实现，避免重复代码）"""
        if hasattr(self.llm_provider, '_estimate_messages_tokens') and self.llm_provider:
            return self.llm_provider._estimate_messages_tokens(messages)
        return self._estimate_tokens_fallback(messages)

    @staticmethod

    def _estimate_tokens_fallback(messages: List[Dict]) -> int:
        return PromptComposer.estimate_tokens_fallback(messages)

    def _estimate_text_tokens(text: str) -> int:
        return PromptComposer.estimate_text_tokens(text)

    def _prune_tool_cache(self):
        """限制工具缓存大小，淘汰最久未使用的条目"""
        if len(self._tool_cache) <= self._max_tool_cache:
            return
        evict_count = len(self._tool_cache) - self._max_tool_cache + 50
        sorted_items = sorted(
            self._tool_cache.items(),
            key=lambda kv: self._last_tool_call_time.get(kv[0], 0)
        )
        for key, _ in sorted_items[:evict_count]:
            self._tool_cache.pop(key, None)
            self._last_tool_call_time.pop(key, None)

    def _log_token_usage(self, query: str, estimated_tokens: int, messages: List[Dict]):
        try:
            entry = {
                "timestamp": datetime.now().isoformat(),
                "query_preview": query[:80],
                "estimated_tokens": estimated_tokens,
                "message_count": len(messages),
                "role": self.current_role,
                "locale": self.current_locale
            }
            self._token_log.append(entry)
            if len(self._token_log) > 200:
                self._token_log = self._token_log[-200:]
            # 持久化到 JSON 文件供 API 端点和跨会话统计使用
            self._persist_token_log(entry)
        except Exception:
            logger.warning("Token log append failed")

    def _persist_token_log(self, new_entry: dict):
        """将 token 使用记录增量写入 token_usage.json"""
        if not self._token_log_file_path:
            return
        try:
            existing = []
            if self._token_log_file_path.exists():
                raw = self._token_log_file_path.read_text(encoding="utf-8")
                if raw.strip():
                    existing = json.loads(raw)
            existing.append(new_entry)
            # 仅保留最近 7 天数据
            cutoff = (datetime.now() - timedelta(days=7)).isoformat()
            existing = [e for e in existing if e.get("timestamp", "") >= cutoff]
            self._token_log_file_path.write_text(
                json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.warning("Token log persist failed")

    def _log_tool_feedback(self, tool_name: str, input_args: dict, output: str):
        self._tool_loop_engine.log_tool_feedback(tool_name, input_args, output)
        self._log_tool_feedback_cache.append({
            "tool": tool_name,
            "input": str(input_args)[:200],
            "output": str(output)[:200],
            "timestamp": time.time()
        })
        if len(self._log_tool_feedback_cache) > 100:
            self._log_tool_feedback_cache = self._log_tool_feedback_cache[-100:]

    def _validate_optimization_json(self, raw_output: str) -> Optional[Dict]:
        """校验优化 JSON（转发到 EvolutionService）"""
        if self._evolution_service:
            return self._evolution_service._validate_optimization_json(raw_output)
        from ..evolution_service import EvolutionService
        return EvolutionService._validate_optimization_json(raw_output)

    async def _curator_check(self) -> int:
        """执行技能策展检查（委托给 EvolutionService）"""
        if not self._evolution_service:
            return 0
        return await self._evolution_service.curator_check()

    async def _auto_fix_tool(self, tool_name: str, error: Exception = None, input_args: Dict = None) -> Optional[str]:
        """自动修复工具（委托给 EvolutionService）"""
        if not self._evolution_service:
            return None
        return await self._evolution_service.auto_fix_tool(tool_name, error, input_args or {})

    async def execute_tool_with_retry(self, tool_name: str, arguments: Dict[str, Any], max_retries: int = 2) -> str:
        result = await self._tool_loop_engine.execute_tool_with_retry(tool_name, arguments, max_retries)
        if self._evolution_tester:
            self._evolution_tester.record_from_execution(tool_name, arguments, result, True)
        return result

    @property
    def _refresh_static_prompt(self):
        pass

    def _invalidate_prompt_cache(self):
        if self._prompt_composer:
            self._prompt_composer.invalidate_cache()

    async def stop_active_requests(self):
        for task in self._active_requests:
            if not task.done():
                task.cancel()
        self._active_requests.clear()
