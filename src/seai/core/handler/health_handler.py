"""
健康检查处理器
提供 /api/health 端点的请求处理逻辑
"""
from fastapi import APIRouter
from ..service.health_service import HealthService

router = APIRouter(tags=["系统"])

_health_service: HealthService = None


def init_health_handler(health_service: HealthService):
    global _health_service
    _health_service = health_service


@router.get("/api/health")
async def health_check():
    if _health_service is None:
        return {"status": "starting", "uptime": 0}
    return _health_service.check()