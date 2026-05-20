"""
CircuitBreaker 单元测试
"""
import pytest
import time
from seai.core.circuit_breaker import CircuitBreaker, CircuitBreakerManager, CircuitState


class TestCircuitBreaker:
    """熔断器单元测试"""

    def test_initial_state(self):
        breaker = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=1.0)
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0
        assert breaker.can_execute() is True

    def test_success_resets_failure_count(self):
        breaker = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=1.0)
        breaker.on_failure()
        breaker.on_failure()
        assert breaker.failure_count == 2
        breaker.on_success()
        assert breaker.failure_count == 1
        breaker.on_success()
        assert breaker.failure_count == 0
        assert breaker.success_count == 2

    def test_opens_after_threshold(self):
        breaker = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=1.0)
        breaker.on_failure()
        breaker.on_failure()
        breaker.on_failure()
        assert breaker.state == CircuitState.OPEN
        assert breaker.can_execute() is False

    def test_half_open_after_cooldown(self):
        breaker = CircuitBreaker("test", failure_threshold=2, cooldown_seconds=0.1)
        breaker.on_failure()
        breaker.on_failure()
        assert breaker.state == CircuitState.OPEN
        time.sleep(0.15)
        assert breaker.can_execute() is True
        assert breaker.state == CircuitState.HALF_OPEN

    def test_half_open_success_closes(self):
        breaker = CircuitBreaker("test", failure_threshold=2, cooldown_seconds=0.1)
        breaker.on_failure()
        breaker.on_failure()
        time.sleep(0.15)
        assert breaker.can_execute() is True
        breaker.on_success()
        breaker.on_success()
        breaker.on_success()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0

    def test_half_open_failure_reopens(self):
        breaker = CircuitBreaker("test", failure_threshold=2, cooldown_seconds=0.1)
        breaker.on_failure()
        breaker.on_failure()
        time.sleep(0.15)
        assert breaker.can_execute() is True
        breaker.on_failure()
        assert breaker.state == CircuitState.OPEN

    def test_reset(self):
        breaker = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=1.0)
        breaker.on_failure()
        breaker.on_failure()
        breaker.on_failure()
        assert breaker.state == CircuitState.OPEN
        breaker.reset()
        assert breaker.state == CircuitState.CLOSED
        assert breaker.failure_count == 0
        assert breaker.success_count == 0

    def test_get_stats(self):
        breaker = CircuitBreaker("test", failure_threshold=3, cooldown_seconds=1.0)
        breaker.on_failure()
        breaker.on_success()
        stats = breaker.get_stats()
        assert stats.state == CircuitState.CLOSED
        assert stats.failure_count == 0
        assert stats.success_count == 1


class TestCircuitBreakerManager:
    """熔断器管理器单元测试"""

    def test_get_or_create(self):
        manager = CircuitBreakerManager()
        b1 = manager.get_or_create("svc1", failure_threshold=3, cooldown_seconds=30.0)
        b2 = manager.get_or_create("svc1")
        assert b1 is b2
        b3 = manager.get_or_create("svc2")
        assert b1 is not b3

    def test_get_all_stats(self):
        manager = CircuitBreakerManager()
        manager.get_or_create("a")
        manager.get_or_create("b")
        stats = manager.get_all_stats()
        assert "a" in stats
        assert "b" in stats

    def test_reset_all(self):
        manager = CircuitBreakerManager()
        b = manager.get_or_create("test", failure_threshold=2, cooldown_seconds=1.0)
        b.on_failure()
        b.on_failure()
        assert b.state == CircuitState.OPEN
        manager.reset_all()
        assert b.state == CircuitState.CLOSED
