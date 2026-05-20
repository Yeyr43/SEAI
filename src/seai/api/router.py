# ══════════════════════════════════════════════════
# api/router.py - Main API router
# ────────────────────────────────────────────────
# Creates an APIRouter that includes every
# sub-router (chat, sessions, skills, models,
# backup, system, logs, whitelist).
# ══════════════════════════════════════════════════
from fastapi import APIRouter

from .chat import router as _chat_router
from .sessions import router as _sessions_router
from .skills import router as _skills_router
from .models import router as _models_router
from .backup import router as _backup_router
from .system import router as _system_router
from .logs import router as _logs_router
from .whitelist import router as _whitelist_router


def create_api_router() -> APIRouter:
    """Return an APIRouter with all API sub-routers included."""
    router = APIRouter()

    router.include_router(_chat_router, tags=["对话", "工具", "调试"])
    router.include_router(_sessions_router, tags=["会话"])
    router.include_router(_skills_router, tags=["技能"])
    router.include_router(_models_router, tags=["模型"])
    router.include_router(_backup_router, tags=["备份"])
    router.include_router(_system_router, tags=[
        "设置", "系统", "进化", "多Agent", "SEAT",
        "工作流", "待办", "反馈", "数据库",
        "知识图谱", "记忆", "插件", "补丁",
        "渠道", "MCP", "任务",
    ])
    router.include_router(_logs_router, tags=["日志"])
    router.include_router(_whitelist_router, tags=["白名单"])

    return router
