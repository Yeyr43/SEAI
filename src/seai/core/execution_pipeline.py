"""
SEAI 执行管道 - 统一执行管道 + 中间件链 + 策略模式
提供可组合的执行流程，支持横切关注点注入
"""
import asyncio
import time
import uuid
from typing import Dict, List, Callable, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field
from enum import Enum
from abc import ABC, abstractmethod
from loguru import logger


class PipelinePhase(str, Enum):
    PRE_PROCESS = "pre_process"
    EXECUTE = "execute"
    POST_PROCESS = "post_process"
    ERROR = "error"


@dataclass
class PipelineContext:
    query: str
    history: List[Dict] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    start_time: float = field(default_factory=time.time)
    phase: PipelinePhase = PipelinePhase.PRE_PROCESS
    result: Any = None
    error: Optional[Exception] = None
    cancelled: bool = False
    metrics: Dict[str, Any] = field(default_factory=dict)

    def elapsed_ms(self) -> float:
        return (time.time() - self.start_time) * 1000

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "query": self.query[:200],
            "phase": self.phase.value,
            "elapsed_ms": round(self.elapsed_ms(), 2),
            "has_error": self.error is not None,
            "cancelled": self.cancelled,
            "metrics": self.metrics,
        }


class Middleware(ABC):
    """中间件基类 - 可插入执行管道的横切关注点"""

    @abstractmethod
    async def process(self, context: PipelineContext, next_handler: Callable) -> Any:
        pass


class LoggingMiddleware(Middleware):
    """日志中间件 - 记录请求/响应"""

    async def process(self, context: PipelineContext, next_handler: Callable) -> Any:
        logger.info(f"[Pipeline] 开始处理 [{context.request_id}]: {context.query[:100]}")
        try:
            result = await next_handler(context)
            logger.info(f"[Pipeline] 完成处理 [{context.request_id}]: {context.elapsed_ms():.0f}ms")
            return result
        except Exception as e:
            logger.error(f"[Pipeline] 处理异常 [{context.request_id}]: {e}")
            raise


class MetricsMiddleware(Middleware):
    """指标中间件 - 收集性能指标"""

    def __init__(self):
        self._metrics: List[dict] = []
        self._max_metrics = 500

    async def process(self, context: PipelineContext, next_handler: Callable) -> Any:
        try:
            result = await next_handler(context)
            context.metrics["success"] = True
            return result
        except Exception as e:
            context.metrics["success"] = False
            context.metrics["error_type"] = type(e).__name__
            raise
        finally:
            self._record(context)

    def _record(self, context: PipelineContext):
        self._metrics.append({
            "request_id": context.request_id,
            "elapsed_ms": context.elapsed_ms(),
            "success": context.metrics.get("success", False),
            "query_length": len(context.query),
            "history_count": len(context.history),
            "timestamp": time.time(),
        })
        if len(self._metrics) > self._max_metrics:
            self._metrics = self._metrics[-self._max_metrics:]

    def get_stats(self) -> dict:
        if not self._metrics:
            return {"total": 0}
        successes = [m for m in self._metrics if m["success"]]
        latencies = [m["elapsed_ms"] for m in self._metrics]
        return {
            "total": len(self._metrics),
            "success_rate": len(successes) / len(self._metrics) if self._metrics else 0,
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0,
            "p95_latency_ms": round(sorted(latencies)[min(int(len(latencies) * 0.95), len(latencies) - 1)], 2) if latencies else 0,
            "p99_latency_ms": round(sorted(latencies)[min(int(len(latencies) * 0.99), len(latencies) - 1)], 2) if latencies else 0,
        }


class ConstraintMiddleware(Middleware):
    """约束中间件 - 在管道中执行约束检查"""

    def __init__(self, constraint_engine=None):
        self.constraint_engine = constraint_engine

    async def process(self, context: PipelineContext, next_handler: Callable) -> Any:
        if self.constraint_engine:
            check = self.constraint_engine.check_query(context.query)
            if not check.passed:
                logger.warning(f"[Pipeline] 约束检查未通过 [{context.request_id}]: {check.reason}")
                context.error = Exception(f"约束检查未通过: {check.reason}")
                return f"请求被拒绝: {check.reason}"
        return await next_handler(context)


class CircuitBreakerMiddleware(Middleware):
    """熔断中间件 - 在管道中集成熔断保护"""

    def __init__(self, breaker=None):
        self.breaker = breaker

    async def process(self, context: PipelineContext, next_handler: Callable) -> Any:
        if self.breaker and not self.breaker.can_execute():
            logger.warning(f"[Pipeline] 熔断保护触发 [{context.request_id}]")
            context.error = Exception("熔断保护已触发")
            return "服务暂时不可用（熔断保护已触发），请稍后重试"
        try:
            result = await next_handler(context)
            if self.breaker:
                self.breaker.on_success()
            return result
        except Exception as e:
            if self.breaker:
                self.breaker.on_failure()
            raise


class ExecutionStrategy(ABC):
    """执行策略基类"""

    @abstractmethod
    async def execute(self, context: PipelineContext) -> Any:
        pass


class SingleAgentStrategy(ExecutionStrategy):
    """单 Agent 执行策略"""

    def __init__(self, agent):
        self.agent = agent

    async def execute(self, context: PipelineContext) -> Any:
        messages = self.agent._build_messages(context.query, context.history)
        tools = self.agent._collect_relevant_tools(context.query)
        return await self.agent._process_sync(messages, tools)


class MultiAgentStrategy(ExecutionStrategy):
    """多 Agent 执行策略"""

    def __init__(self, agent):
        self.agent = agent

    async def execute(self, context: PipelineContext) -> Any:
        result_chunks = []
        async for chunk in self.agent._process_multi_agent(
            context.query, context.history, stream=False
        ):
            result_chunks.append(chunk)
        return "".join(result_chunks)


class StreamStrategy(ExecutionStrategy):
    """流式执行策略"""

    def __init__(self, agent):
        self.agent = agent

    async def execute(self, context: PipelineContext) -> AsyncGenerator[str, None]:
        messages = self.agent._build_messages(context.query, context.history)
        tools = self.agent._collect_relevant_tools(context.query)
        async for chunk in self.agent._process_stream(messages, tools):
            yield chunk


class ExecutionPipeline:
    """统一执行管道 - 中间件链 + 策略路由"""

    def __init__(self, agent=None):
        self.agent = agent
        self._middlewares: List[Middleware] = []
        self._strategies: Dict[str, ExecutionStrategy] = {}
        self._default_strategy: Optional[ExecutionStrategy] = None
        self._metrics_middleware: Optional[MetricsMiddleware] = None

    def use(self, middleware: Middleware):
        self._middlewares.append(middleware)
        if isinstance(middleware, MetricsMiddleware):
            self._metrics_middleware = middleware

    def register_strategy(self, name: str, strategy: ExecutionStrategy):
        self._strategies[name] = strategy

    def set_default_strategy(self, strategy: ExecutionStrategy):
        self._default_strategy = strategy

    async def execute(
        self,
        query: str,
        history: List[Dict] = None,
        strategy_name: str = None,
        metadata: Dict[str, Any] = None,
    ) -> Any:
        context = PipelineContext(
            query=query,
            history=history or [],
            metadata=metadata or {},
        )

        strategy = self._strategies.get(strategy_name) if strategy_name else self._default_strategy
        if not strategy:
            raise ValueError(f"未找到执行策略: {strategy_name}")

        handler = self._build_handler(strategy)
        return await self._execute_chain(context, handler)

    async def execute_stream(
        self,
        query: str,
        history: List[Dict] = None,
        strategy_name: str = None,
        metadata: Dict[str, Any] = None,
    ) -> AsyncGenerator[str, None]:
        context = PipelineContext(
            query=query,
            history=history or [],
            metadata=metadata or {},
        )

        strategy = self._strategies.get(strategy_name) if strategy_name else self._default_strategy
        if not strategy:
            raise ValueError(f"未找到执行策略: {strategy_name}")

        if not isinstance(strategy, StreamStrategy):
            result = await self.execute(query, history, strategy_name, metadata)
            yield result
            return

        # 非流式的中间件链贯穿执行（约束检查、熔断、日志、指标）
        # 流式模式下：先跑前置中间件，流式执行，再跑后置中间件
        async def _noop_handler(ctx):
            pass

        if self._middlewares:
            # 在前置中间件之后立即检查阻断
            blocked = False
            for middleware in self._middlewares:
                try:
                    await middleware.process(context, _noop_handler)
                except Exception as e:
                    context.error = e
                    context.phase = PipelinePhase.ERROR
                    blocked = True
                    break

                if context.error or context.cancelled:
                    blocked = True
                    break

                if isinstance(middleware, CircuitBreakerMiddleware):
                    if middleware.breaker and not middleware.breaker.can_execute():
                        blocked = True
                        break

            if blocked:
                error_msg = str(context.error) if context.error else "请求已被拒绝"
                yield error_msg
                return

        # 流式执行
        try:
            async for chunk in strategy.execute(context):
                yield chunk
            if not context.error:
                context.metrics["success"] = True
        except Exception as e:
            context.metrics["success"] = False
            context.metrics["error_type"] = type(e).__name__
            context.error = e
            yield f"流式执行异常: {str(e)}"

        # 后置中间件（日志、指标记录）
        for middleware in self._middlewares:
            if isinstance(middleware, LoggingMiddleware):
                logger.info(f"[Pipeline] 流式完成 [{context.request_id}]: {context.elapsed_ms():.0f}ms")
            elif isinstance(middleware, MetricsMiddleware):
                middleware._record(context)

    def _build_handler(self, strategy: ExecutionStrategy) -> Callable:
        async def handler(ctx: PipelineContext) -> Any:
            ctx.phase = PipelinePhase.EXECUTE
            return await strategy.execute(ctx)
        return handler

    async def _execute_chain(self, context: PipelineContext, handler: Callable) -> Any:
        if not self._middlewares:
            return await handler(context)

        chain = handler
        for middleware in reversed(self._middlewares):
            def make_bound_chain(mw, nxt):
                return lambda ctx: mw.process(ctx, nxt)
            chain = make_bound_chain(middleware, chain)

        return await chain(context)

    def get_metrics(self) -> dict:
        if self._metrics_middleware:
            return self._metrics_middleware.get_stats()
        return {}

    def get_pipeline_info(self) -> dict:
        return {
            "middlewares": [type(m).__name__ for m in self._middlewares],
            "strategies": list(self._strategies.keys()),
            "default_strategy": type(self._default_strategy).__name__ if self._default_strategy else None,
        }