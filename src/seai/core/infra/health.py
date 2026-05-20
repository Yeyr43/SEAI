"""
SEAI 健康检查系统 - 组件状态监控与故障检测
支持并行健康检查、分级状态报告、自动告警
"""
import asyncio
import time
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from loguru import logger


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthReport:
    component: str
    status: HealthStatus
    message: str = ""
    latency_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "status": self.status.value,
            "message": self.message,
            "latency_ms": round(self.latency_ms, 2),
            "details": self.details,
            "timestamp": self.timestamp,
            "dependencies": self.dependencies,
        }


@dataclass
class SystemHealth:
    status: HealthStatus
    components: List[HealthReport]
    timestamp: float = field(default_factory=time.time)
    total_latency_ms: float = 0.0

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "timestamp": self.timestamp,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "components": [c.to_dict() for c in self.components],
            "summary": {
                "total": len(self.components),
                "healthy": sum(1 for c in self.components if c.status == HealthStatus.HEALTHY),
                "degraded": sum(1 for c in self.components if c.status == HealthStatus.DEGRADED),
                "unhealthy": sum(1 for c in self.components if c.status == HealthStatus.UNHEALTHY),
            },
        }


class HealthChecker:
    """健康检查器 - 并行检查所有注册组件"""

    def __init__(self):
        self._checks: Dict[str, Callable] = {}
        self._dependencies: Dict[str, List[str]] = {}
        self._timeout: float = 5.0
        self._history: List[SystemHealth] = []
        self._max_history = 50

    def register(
        self,
        component: str,
        check_fn: Callable,
        dependencies: List[str] = None,
    ):
        self._checks[component] = check_fn
        if dependencies:
            self._dependencies[component] = dependencies

    def unregister(self, component: str):
        self._checks.pop(component, None)
        self._dependencies.pop(component, None)

    async def check_all(self) -> SystemHealth:
        start = time.time()
        components = await self._run_checks()
        total_latency = (time.time() - start) * 1000

        statuses = [c.status for c in components]
        if HealthStatus.UNHEALTHY in statuses:
            overall = HealthStatus.UNHEALTHY
        elif HealthStatus.DEGRADED in statuses:
            overall = HealthStatus.DEGRADED
        elif all(s == HealthStatus.HEALTHY for s in statuses):
            overall = HealthStatus.HEALTHY
        else:
            overall = HealthStatus.UNKNOWN

        result = SystemHealth(
            status=overall,
            components=components,
            total_latency_ms=total_latency,
        )

        self._history.append(result)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        if overall != HealthStatus.HEALTHY:
            unhealthy = [c.component for c in components if c.status != HealthStatus.HEALTHY]
            logger.warning(f"健康检查发现问题: {unhealthy}")

        return result

    async def check_component(self, component: str) -> HealthReport:
        if component not in self._checks:
            return HealthReport(
                component=component,
                status=HealthStatus.UNKNOWN,
                message="组件未注册",
            )

        return await self._run_single_check(component)

    async def _run_checks(self) -> List[HealthReport]:
        checked: Dict[str, HealthReport] = {}
        remaining = set(self._checks.keys())

        while remaining:
            ready = {
                name for name in remaining
                if all(d in checked for d in self._dependencies.get(name, []))
            }

            if not ready:
                for name in remaining:
                    checked[name] = HealthReport(
                        component=name,
                        status=HealthStatus.UNHEALTHY,
                        message="循环依赖或依赖缺失",
                    )
                break

            tasks = [self._run_single_check(name) for name in ready]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for name, result in zip(ready, results):
                if isinstance(result, Exception):
                    checked[name] = HealthReport(
                        component=name,
                        status=HealthStatus.UNHEALTHY,
                        message=str(result),
                    )
                else:
                    checked[name] = result

            remaining -= ready

        return [checked[name] for name in self._checks.keys()]

    async def _run_single_check(self, component: str) -> HealthReport:
        check_fn = self._checks[component]
        start = time.time()

        try:
            result = await asyncio.wait_for(
                self._safe_check(check_fn),
                timeout=self._timeout,
            )
            latency = (time.time() - start) * 1000

            if isinstance(result, HealthReport):
                result.latency_ms = latency
                return result
            if isinstance(result, dict):
                return HealthReport(
                    component=component,
                    status=HealthStatus(result.get("status", "healthy")),
                    message=result.get("message", ""),
                    latency_ms=latency,
                    details=result.get("details", {}),
                )
            if isinstance(result, bool):
                return HealthReport(
                    component=component,
                    status=HealthStatus.HEALTHY if result else HealthStatus.UNHEALTHY,
                    latency_ms=latency,
                )
            return HealthReport(
                component=component,
                status=HealthStatus.HEALTHY,
                latency_ms=latency,
            )

        except asyncio.TimeoutError:
            return HealthReport(
                component=component,
                status=HealthStatus.UNHEALTHY,
                message=f"健康检查超时 ({self._timeout}s)",
                latency_ms=self._timeout * 1000,
            )
        except Exception as e:
            return HealthReport(
                component=component,
                status=HealthStatus.UNHEALTHY,
                message=str(e),
                latency_ms=(time.time() - start) * 1000,
            )

    async def _safe_check(self, check_fn: Callable):
        result = check_fn()
        if asyncio.iscoroutine(result):
            result = await result
        return result

    def get_history(self, limit: int = 10) -> List[dict]:
        return [h.to_dict() for h in self._history[-limit:]]

    def get_latest(self) -> Optional[dict]:
        if self._history:
            return self._history[-1].to_dict()
        return None


health_checker = HealthChecker()