"""
测试 SEAI 健康检查系统
"""
import asyncio
import pytest
from seai.core.health_check import HealthChecker, HealthReport, HealthStatus, SystemHealth


class TestHealthChecker:
    def setup_method(self):
        self.checker = HealthChecker()

    def test_register_and_check(self):
        async def healthy_check():
            return HealthReport(component="test", status=HealthStatus.HEALTHY, message="OK")

        self.checker.register("test", healthy_check)
        result = asyncio.run(self.checker.check_all())

        assert result.status == HealthStatus.HEALTHY
        assert len(result.components) == 1
        assert result.components[0].status == HealthStatus.HEALTHY

    def test_unhealthy_component(self):
        async def unhealthy_check():
            return HealthReport(component="bad", status=HealthStatus.UNHEALTHY, message="Down")

        self.checker.register("bad", unhealthy_check)
        result = asyncio.run(self.checker.check_all())

        assert result.status == HealthStatus.UNHEALTHY

    def test_degraded_status(self):
        async def healthy_check():
            return HealthReport(component="good", status=HealthStatus.HEALTHY)

        async def degraded_check():
            return HealthReport(component="slow", status=HealthStatus.DEGRADED, message="Slow")

        self.checker.register("good", healthy_check)
        self.checker.register("slow", degraded_check)
        result = asyncio.run(self.checker.check_all())

        assert result.status == HealthStatus.DEGRADED

    def test_dict_result(self):
        async def dict_check():
            return {"status": "healthy", "message": "All good", "details": {"cpu": 50}}

        self.checker.register("dict_test", dict_check)
        result = asyncio.run(self.checker.check_all())

        assert result.components[0].status == HealthStatus.HEALTHY
        assert result.components[0].details["cpu"] == 50

    def test_bool_result(self):
        async def bool_check():
            return True

        self.checker.register("bool_test", bool_check)
        result = asyncio.run(self.checker.check_all())

        assert result.components[0].status == HealthStatus.HEALTHY

    def test_timeout(self):
        self.checker._timeout = 0.1

        async def slow_check():
            await asyncio.sleep(1.0)
            return HealthReport(component="slow", status=HealthStatus.HEALTHY)

        self.checker.register("slow", slow_check)
        result = asyncio.run(self.checker.check_all())

        assert result.components[0].status == HealthStatus.UNHEALTHY
        assert "超时" in result.components[0].message

    def test_exception_handling(self):
        async def error_check():
            raise RuntimeError("test error")

        self.checker.register("error", error_check)
        result = asyncio.run(self.checker.check_all())

        assert result.components[0].status == HealthStatus.UNHEALTHY
        assert "test error" in result.components[0].message

    def test_dependency_order(self):
        order = []

        async def check_a():
            order.append("a")
            return HealthReport(component="a", status=HealthStatus.HEALTHY)

        async def check_b():
            order.append("b")
            return HealthReport(component="b", status=HealthStatus.HEALTHY)

        self.checker.register("a", check_a)
        self.checker.register("b", check_b, dependencies=["a"])
        asyncio.run(self.checker.check_all())

        assert order[0] == "a"
        assert order[1] == "b"

    def test_unregister(self):
        async def check():
            return HealthReport(component="test", status=HealthStatus.HEALTHY)

        self.checker.register("test", check)
        self.checker.unregister("test")
        result = asyncio.run(self.checker.check_all())

        assert len(result.components) == 0

    def test_check_single_component(self):
        async def check():
            return HealthReport(component="single", status=HealthStatus.HEALTHY, message="OK")

        self.checker.register("single", check)
        report = asyncio.run(self.checker.check_component("single"))

        assert report.status == HealthStatus.HEALTHY
        assert report.component == "single"

    def test_check_unknown_component(self):
        report = asyncio.run(self.checker.check_component("unknown"))
        assert report.status == HealthStatus.UNKNOWN

    def test_system_health_to_dict(self):
        async def check():
            return HealthReport(component="test", status=HealthStatus.HEALTHY)

        self.checker.register("test", check)
        result = asyncio.run(self.checker.check_all())
        d = result.to_dict()

        assert d["status"] == "healthy"
        assert d["summary"]["total"] == 1
        assert d["summary"]["healthy"] == 1

    def test_history(self):
        async def check():
            return HealthReport(component="test", status=HealthStatus.HEALTHY)

        self.checker.register("test", check)
        for _ in range(3):
            asyncio.run(self.checker.check_all())

        history = self.checker.get_history()
        assert len(history) == 3

    def test_get_latest(self):
        async def check():
            return HealthReport(component="test", status=HealthStatus.HEALTHY)

        self.checker.register("test", check)
        asyncio.run(self.checker.check_all())

        latest = self.checker.get_latest()
        assert latest is not None
        assert latest["status"] == "healthy"