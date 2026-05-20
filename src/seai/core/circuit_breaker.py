"""
熔断器模块 - 为关键操作提供故障隔离和自动恢复
防止单点故障扩散，保护系统稳定性
"""
import time
import asyncio
from enum import Enum
from typing import Dict, Optional
from dataclasses import dataclass


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitStats:
    state: CircuitState
    failure_count: int
    success_count: int
    last_failure_time: float
    last_success_time: float
    opened_at: Optional[float] = None


class CircuitBreaker:
    """熔断器：连续失败 N 次后自动熔断，定时尝试恢复"""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        half_open_max_requests: int = 3
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.half_open_max_requests = half_open_max_requests

        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
        self.last_success_time = 0.0
        self.opened_at: Optional[float] = None
        self._half_open_requests = 0

    def can_execute(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            if time.time() - (self.opened_at or 0) >= self.cooldown_seconds:
                self.state = CircuitState.HALF_OPEN
                self._half_open_requests = 0
                return True
            return False

        if self.state == CircuitState.HALF_OPEN:
            return self._half_open_requests < self.half_open_max_requests

        return True

    def on_success(self):
        self.success_count += 1
        self.last_success_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            self._half_open_requests += 1
            if self._half_open_requests >= self.half_open_max_requests:
                self.state = CircuitState.CLOSED
                self.failure_count = 0

        self.failure_count = max(0, self.failure_count - 1)

    def on_failure(self):
        self.failure_count += 1
        self.last_failure_time = time.time()

        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.OPEN
            self.opened_at = time.time()
        elif self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            self.opened_at = time.time()

    def reset(self):
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.opened_at = None
        self._half_open_requests = 0

    def get_stats(self) -> CircuitStats:
        return CircuitStats(
            state=self.state,
            failure_count=self.failure_count,
            success_count=self.success_count,
            last_failure_time=self.last_failure_time,
            last_success_time=self.last_success_time,
            opened_at=self.opened_at
        )


class CircuitBreakerManager:
    """熔断器管理器：统一管理多个熔断器"""

    def __init__(self):
        self._breakers: Dict[str, CircuitBreaker] = {}

    def get_or_create(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0
    ) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds
            )
        return self._breakers[name]

    def get_all_stats(self) -> Dict[str, CircuitStats]:
        return {name: breaker.get_stats() for name, breaker in self._breakers.items()}

    def reset_all(self):
        for breaker in self._breakers.values():
            breaker.reset()


breaker_manager = CircuitBreakerManager()
