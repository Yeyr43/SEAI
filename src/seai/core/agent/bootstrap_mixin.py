""""""
from ..seat import SEATEngine
from ..circuit_breaker import CircuitBreaker
from ..constraint_engine import ConstraintEngine
from ..context_retriever import ContextRetriever
from ..conversation_service import ConversationService
from ..error_handler import SmartErrorHandler
from ..event_bus import event_bus
from ..evolution_service import EvolutionService
from ..evolution_tester import EvolutionTester
from ..execution_pipeline import CircuitBreakerMiddleware
from ..execution_pipeline import ConstraintMiddleware
from ..execution_pipeline import ExecutionPipeline
from ..execution_pipeline import LoggingMiddleware
from ..execution_pipeline import MetricsMiddleware
from ..execution_pipeline import MultiAgentStrategy
from ..execution_pipeline import SingleAgentStrategy
from ..execution_pipeline import StreamStrategy
from ..feedback_loop import FeedbackLoop
from ..interfaces.memory_store import MemoryStore
from ..knowledge_graph import KnowledgeGraphManager
from ..media_encoder import MediaEncoder
from ..message_builder import MessageBuilder
from ..prompt_composer import PromptComposer
from ..reflection_engine import ReflectionEngine
from ..sub_agent import AgentPool
from ..sub_agent import ParallelScheduler
from ..sub_agent import ResultMerger
from ..sub_agent import TaskComplexityEstimator
from ..sub_agent import TaskDecomposer
from ..tool_loop import ToolLoopEngine
from loguru import logger
from pathlib import Path
import asyncio
import json
import sys

class BootstrapMixin:
    async def initialize(self) -> bool:
        """初始化智能体"""
        success = await self.lifecycle_manager.initialize()
        if success:
            self.lifecycle_manager.set_agent(self)
            self.llm_provider = self.lifecycle_manager.llm_provider
            self.memory_store = self.lifecycle_manager.memory_store
            self.tool_executor = self.lifecycle_manager.tool_executor
            self.skill_repository = self.lifecycle_manager.skill_repository

            # 统一在 initialize() 中初始化知识图谱（与 MemoryStore 一致）
            from ..knowledge_graph import KnowledgeGraphManager
            self.knowledge_graph_manager = KnowledgeGraphManager(
                self.data_dir / "knowledge_graph"
            )
            self.knowledge_graph_manager.initialize()

            self._init_prompt_engine()

            # 初始化从 agent.py 提取的协作文档
            self._context_retriever = ContextRetriever(
                memory_store=self.memory_store,
                session_manager=self.session_manager,
                knowledge_graph_manager=self.knowledge_graph_manager,
            )
            self._prompt_composer = PromptComposer(
                prompt_engine=self._prompt_engine,
                memory_store=self.memory_store,
            )
            self._media_encoder = MediaEncoder(memory_store=self.memory_store)

            system_config = self.config.get_system_config()
            self._error_handler = SmartErrorHandler(system_config.data_dir)
            self._evolution_tester = EvolutionTester(system_config.data_dir)

            self.security.load_config(self.load_config())

            self._init_multi_agent()

            self._conversation_service = ConversationService(
                session_manager=self.session_manager,
                llm_provider=self.llm_provider,
                data_dir=self.data_dir,
            )

            self._evolution_service = EvolutionService(
                llm_provider=self.llm_provider,
                skill_repository=self.skill_repository,
                memory_store=self.memory_store,
                error_handler=self._error_handler,
                evolution_tester=self._evolution_tester,
                data_dir=self.data_dir,
                config=self.config,
            )

            self._init_pipeline()

            self._init_seat()

            # 初始化第三方引擎（strangler fig 模式）
            from ..message_builder import MessageBuilder
            from ..tool_loop import ToolLoopEngine
            from ..reflection_engine import ReflectionEngine
            self._message_builder = MessageBuilder(
                llm_provider=self.llm_provider,
                memory_store=self.memory_store,
                prompt_engine=self._prompt_engine,
                kg_provider=self.knowledge_graph_manager,
                skill_repository=self.skill_repository,
                config=self.config,
            )

            # 引擎选择：配置中 engine: "ooda" 切换为 OODA 引擎
            config = self.load_config()
            engine_type = config.get("engine", "default")
            engine_kwargs = dict(
                llm_provider=self.llm_provider,
                tool_executor=self.tool_executor,
                skill_system=self.skill_system,
                skill_repository=self.skill_repository,
                memory_store=self.memory_store,
                error_handler=self._error_handler,
                evolution_service=self._evolution_service,
                conversation_service=self._conversation_service,
                feedback_loop=self._feedback_loop,
                data_dir=self.data_dir,
                circuit_breaker=self._llm_breaker,
                security=self.security,
            )
            if engine_type == "ooda":
                try:
                    from ..tool_loop.ooda_loop import OODAToolLoopEngine
                    self._tool_loop_engine = OODAToolLoopEngine(**engine_kwargs)
                    logger.info("OODAToolLoopEngine 已激活")
                except Exception as e:
                    logger.warning(
                        f"OODA 引擎导入失败，回退到 ToolLoopEngine: {e}"
                    )
                    self._tool_loop_engine = ToolLoopEngine(**engine_kwargs)
            else:
                self._tool_loop_engine = ToolLoopEngine(**engine_kwargs)
            self._reflection_engine = ReflectionEngine(
                llm_provider=self.llm_provider,
                memory_store=self.memory_store,
                error_handler=self._error_handler,
                feedback_loop=self._feedback_loop,
                evolution_tester=self._evolution_tester,
                kg_provider=self.knowledge_graph_manager,
                data_dir=self.data_dir,
                config=self.config,
            )

            self._token_log_file_path = self.data_dir / "token_usage.json"

            logger.info("SEAgent 初始化完成")

        return success

    def _init_prompt_engine(self):
        try:
            prompts_dir = Path(__file__).parent.parent / "prompts"
            if prompts_dir.exists():
                sys.path.insert(0, str(prompts_dir))
                from prompt_engine import PromptEngine
                self._prompt_engine = PromptEngine(prompts_dir)
                logger.info(f"PromptEngine 已加载 v{self._prompt_engine.get_version()}")
        except Exception as e:
            logger.warning(f"PromptEngine 加载失败，使用内置提示词: {e}")

    def _init_multi_agent(self):
        config = self.load_config()
        ma_config = config.get("multi_agent", {})
        if ma_config:
            self._multi_agent_config.update(ma_config)

        self._complexity_estimator = TaskComplexityEstimator(
            threshold=self._multi_agent_config["complexity_threshold"]
        )
        self._agent_pool = AgentPool(
            llm_provider=self.llm_provider,
            tool_executor=self.tool_executor,
            max_agents=self._multi_agent_config["max_sub_agents"],
        )
        self._task_decomposer = TaskDecomposer(llm_provider=self.llm_provider)
        self._parallel_scheduler = ParallelScheduler(
            max_concurrent=self._multi_agent_config["max_sub_agents"]
        )
        self._result_merger = ResultMerger(llm_provider=self.llm_provider)

        self._constraint_engine = ConstraintEngine(
            config_path=self.data_dir / "constraint_rules.json"
        )
        self._feedback_loop = FeedbackLoop(event_bus=event_bus)

        self._feedback_loop.register_handler("auto_fix_tool", self._handle_tool_failure_feedback)
        self._feedback_loop.register_handler("light_check", self._handle_light_check_feedback)
        self._feedback_loop.register_handler("deep_evolve", self._handle_deep_evolve_feedback)
        self._feedback_loop.register_handler("security_alert", self._handle_constraint_violation_feedback)

        logger.info(
            f"多 Agent 系统已初始化 (enabled={self._multi_agent_config['enabled']}, "
            f"threshold={self._multi_agent_config['complexity_threshold']}, "
            f"max_agents={self._multi_agent_config['max_sub_agents']})"
        )

    def _init_pipeline(self):
        self._pipeline = ExecutionPipeline(agent=self)

        self._pipeline.use(LoggingMiddleware())
        self._pipeline.use(MetricsMiddleware())
        self._pipeline.use(ConstraintMiddleware(constraint_engine=self._constraint_engine))
        self._pipeline.use(CircuitBreakerMiddleware(breaker=self._llm_breaker))

        self._pipeline.register_strategy("single", SingleAgentStrategy(self))
        self._pipeline.register_strategy("multi", MultiAgentStrategy(self))
        self._pipeline.register_strategy("stream", StreamStrategy(self))
        self._pipeline.set_default_strategy(SingleAgentStrategy(self))

        logger.info("执行管道已初始化")

    def _init_seat(self):
        """初始化 SEAT 多 Agent 团队"""
        try:
            from ..seat import SEATEngine
            self._seat_engine = SEATEngine(
                llm_provider=self.llm_provider,
                tool_executor=self.tool_executor,
                sandbox=getattr(self, '_sandbox', None),
                feedback_loop=self._feedback_loop,
                complexity_estimator=self._complexity_estimator,
            )
            asyncio.create_task(self._seat_engine.start())
            logger.info("SEAT 引擎已初始化")
        except Exception as e:
            logger.warning(f"SEAT 引擎初始化失败（非关键）: {e}")

    async def shutdown(self):
        """关闭智能体"""
        if self._seat_engine:
            await self._seat_engine.stop()
        await self.lifecycle_manager.shutdown()
