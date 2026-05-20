# ══════════════════════════════════════════════════
# api/whitelist.py - Whitelist management endpoints
# ────────────────────────────────────────────────
# GET  /api/whitelist        – get write whitelist
# POST /api/whitelist/add    – add a path to whitelist
# POST /api/whitelist/remove – remove a path from whitelist
# ══════════════════════════════════════════════════
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from . import get_agent

router = APIRouter()


# ── Helper ────────────────────────────────────────

def _reload_security(config: dict):
    """Synchronously update agent and tool_executor security config."""
    agent = get_agent()
    if hasattr(agent, '_security'):
        agent.security.load_config(config)
    if agent.tool_executor and getattr(agent.tool_executor, 'security', None):
        agent.tool_executor.security.load_config(config)


# ── Routes ────────────────────────────────────────

@router.get("/api/whitelist")
async def get_whitelist():
    config = get_agent().load_config()
    security_data = config.get("security", {})
    paths = security_data.get("write_whitelist", [])
    return {"paths": paths}


@router.post("/api/whitelist/add")
async def add_whitelist(data: dict):
    agent = get_agent()
    path = data.get("path", "").strip()
    if not path:
        raise HTTPException(status_code=400, detail="路径不能为空")
    config = agent.load_config()
    security_data = config.get("security", {})
    paths = list(security_data.get("write_whitelist", []))
    if path not in paths:
        paths.append(path)
        security_data["write_whitelist"] = paths
        config["security"] = security_data
        agent.config.save_config()
        _reload_security(config)
    return {"status": "ok", "paths": paths}


@router.post("/api/whitelist/remove")
async def remove_whitelist(data: dict):
    agent = get_agent()
    path = data.get("path", "").strip()
    config = agent.load_config()
    security_data = config.get("security", {})
    paths = list(security_data.get("write_whitelist", []))
    if path in paths:
        paths.remove(path)
        security_data["write_whitelist"] = paths
        config["security"] = security_data
        agent.config.save_config()
        _reload_security(config)
    return {"status": "ok", "paths": paths}
