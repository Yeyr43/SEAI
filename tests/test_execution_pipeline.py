"""
测试 SEAI 执行管道
"""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock
from seai.core.execution_pipeline import (
    ExecutionPipeline, PipelineContext, PipelinePhase,
    LoggingMiddleware, MetricsMiddleware,
    ConstraintMiddleware, CircuitBreakerMiddleware,
    SingleAgentStrategy, MultiAgentStrategy, StreamStrategy,
    Middleware,
)


class TestPipelineContext:
    def test_context_creation(self):
        ctx = PipelineContext(query="test query")
        assert ctx.query == "test query"
        assert ctx.request_id is not None
        assert ctx.phase == PipelinePhase.PRE_PROCESS
        assert ctx.error is None
        assert ctx.cancelled is False

    def test_elapsed_ms(self):
        import time
        ctx = PipelineContext(query="test")
        ctx.start_time = time.time() - 1.0
        assert ctx.elapsed_ms() >= 900

    def test_to_dict(self):
        ctx = PipelineContext(query="test query")
        d = ctx.to_dict()
        assert d["query"] == "test query"
        assert d["phase"] == "pre_process"
        assert d["has_error"] is False


class TestMetricsMiddleware:
    def test_records_metrics(self):
        mw = MetricsMiddleware()
        ctx = PipelineContext(query="test")

        async def handler(c):
            return "result"

        result = asyncio.run(mw.process(ctx, handler))
        assert result == "result"
        assert ctx.metrics["success"] is True

        stats = mw.get_stats()
        assert stats["total"] == 1
        assert stats["success_rate"] == 1.0

    def test_records_failure(self):
        mw = MetricsMiddleware()
        ctx = PipelineContext(query="test")

        async def handler(c):
            raise RuntimeError("fail")

        with pytest.raises(RuntimeError):
            asyncio.run(mw.process(ctx, handler))

        assert ctx.metrics["success"] is False
        assert ctx.metrics["error_type"] == "RuntimeError"


class TestConstraintMiddleware:
    def test_passes_when_no_engine(self):
        mw = ConstraintMiddleware(constraint_engine=None)
        ctx = PipelineContext(query="test")

        async def handler(c):
            return "ok"

        result = asyncio.run(mw.process(ctx, handler))
        assert result == "ok"

    def test_blocks_when_check_fails(self):
        mock_engine = MagicMock()
        mock_check = MagicMock()
        mock_check.passed = False
        mock_check.reason = "blocked"
        mock_engine.check_query.return_value = mock_check

        mw = ConstraintMiddleware(constraint_engine=mock_engine)
        ctx = PipelineContext(query="test")

        async def handler(c):
            return "ok"

        result = asyncio.run(mw.process(ctx, handler))
        assert "拒绝" in result


class TestCircuitBreakerMiddleware:
    def test_passes_when_no_breaker(self):
        mw = CircuitBreakerMiddleware(breaker=None)
        ctx = PipelineContext(query="test")

        async def handler(c):
            return "ok"

        result = asyncio.run(mw.process(ctx, handler))
        assert result == "ok"

    def test_blocks_when_open(self):
        mock_breaker = MagicMock()
        mock_breaker.can_execute.return_value = False

        mw = CircuitBreakerMiddleware(breaker=mock_breaker)
        ctx = PipelineContext(query="test")

        async def handler(c):
            return "ok"

        result = asyncio.run(mw.process(ctx, handler))
        assert "熔断" in result


class TestExecutionPipeline:
    def setup_method(self):
        self.pipeline = ExecutionPipeline()

    def test_register_strategy(self):
        mock_agent = MagicMock()
        strategy = SingleAgentStrategy(mock_agent)
        self.pipeline.register_strategy("single", strategy)
        self.pipeline.set_default_strategy(strategy)

        info = self.pipeline.get_pipeline_info()
        assert "single" in info["strategies"]
        assert info["default_strategy"] == "SingleAgentStrategy"

    def test_pipeline_info(self):
        self.pipeline.use(LoggingMiddleware())
        self.pipeline.use(MetricsMiddleware())

        info = self.pipeline.get_pipeline_info()
        assert "LoggingMiddleware" in info["middlewares"]
        assert "MetricsMiddleware" in info["middlewares"]

    def test_get_metrics_empty(self):
        metrics = self.pipeline.get_metrics()
        assert metrics == {}


class TestLoggingMiddleware:
    def test_logs_request(self):
        mw = LoggingMiddleware()
        ctx = PipelineContext(query="test")

        async def handler(c):
            return "result"

        result = asyncio.run(mw.process(ctx, handler))
        assert result == "result"