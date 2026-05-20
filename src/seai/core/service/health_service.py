"""
健康检查服务
提供系统各组件的健康状态检测
"""
import time
from typing import Dict, Any, Optional
from loguru import logger


class HealthService:
    def __init__(self, agent=None):
        self._agent = agent
        self._startup_time = time.time()

    def set_agent(self, agent):
        self._agent = agent

    def check(self) -> Dict[str, Any]:
        agent = self._agent
        llm_available = False
        memory_available = False
        model = "N/A"
        skills_count = 0

        if agent:
            try:
                llm_available = agent.llm_provider is not None
            except Exception:
                pass
            try:
                memory_available = agent.memory_store is not None
            except Exception:
                pass
            try:
                model = agent.llm_manager.current_model
            except Exception:
                pass
            try:
                skills_count = len(agent.skill_system.skills)
            except Exception:
                pass

        status = "healthy"
        if not llm_available:
            status = "degraded"
        if not llm_available and not memory_available:
            status = "unhealthy"

        return {
            "status": status,
            "model": model,
            "skills_count": skills_count,
            "uptime": round(time.time() - self._startup_time, 1),
            "llm_available": llm_available,
            "memory_available": memory_available,
        }

    def get_uptime(self) -> float:
        return time.time() - self._startup_time