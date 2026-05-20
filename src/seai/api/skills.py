# ══════════════════════════════════════════════════
# api/skills.py - Skills management endpoints
# ────────────────────────────────────────────────
# GET    /api/skills          – get all skills
# POST   /api/skills/toggle   – enable/disable a skill
# DELETE /api/skills/{name}   – delete a skill
# POST   /api/skills/reload   – reload skills from disk
# ══════════════════════════════════════════════════
from __future__ import annotations

from fastapi import APIRouter

from . import get_agent

router = APIRouter()


@router.get("/api/skills")
async def get_skills():
    return get_agent().skill_system.get_all_skills()


@router.post("/api/skills/toggle")
async def toggle_skill(data: dict):
    get_agent().skill_system.set_enabled(data["name"], data["enabled"])
    return {"status": "ok"}


@router.delete("/api/skills/{name}")
async def delete_skill(name: str):
    get_agent().skill_system.delete_skill(name)
    return {"status": "ok"}


@router.post("/api/skills/reload")
async def reload_skills():
    agent = get_agent()
    await agent.skill_repository.load_skills()
    return {"status": "ok"}
