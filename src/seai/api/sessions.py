# ══════════════════════════════════════════════════
# api/sessions.py - Session management endpoints
# ────────────────────────────────────────────────
# GET  /api/sessions                          – list sessions
# POST /api/session/new                       – create session
# GET  /api/session/{id}/history              – get history
# POST /api/session/rename                    – rename session
# POST /api/session/switch                    – switch active session
# POST /api/session/auto_title                – auto-generate title
# DEL  /api/session/{id}                      – delete session
# POST /api/session/context/cleanup           – cleanup orphan context
# GET  /api/session/{id}/context              – get session context
# ══════════════════════════════════════════════════
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import get_agent

router = APIRouter()


# ── Models ────────────────────────────────────────

class RenameRequest(BaseModel):
    session_id: str
    name: str


class SwitchRequest(BaseModel):
    session_id: str


class AutoTitleRequest(BaseModel):
    session_id: str


# ── Routes ────────────────────────────────────────

@router.get("/api/sessions")
async def list_sessions():
    return get_agent().session_manager.list_sessions()


@router.post("/api/session/new")
async def new_session():
    sid = get_agent().new_session()
    return {"session_id": sid}


@router.get("/api/session/{session_id}/history")
async def get_history(session_id: str):
    return {"history": get_agent().session_manager.get_history(session_id)}


@router.post("/api/session/rename")
async def rename_session(req: RenameRequest):
    agent = get_agent()
    agent.session_manager.rename_session(req.session_id, req.name)
    return {"status": "ok"}


@router.post("/api/session/switch")
async def switch_session(req: SwitchRequest):
    get_agent().switch_session(req.session_id)
    return {"status": "ok"}


@router.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    get_agent().delete_session(session_id)
    return {"status": "ok"}


@router.post("/api/session/context/cleanup")
async def cleanup_context_files():
    get_agent().session_manager.cleanup_orphan_context_files()
    return {"status": "ok"}


@router.get("/api/session/{session_id}/context")
async def get_session_context(session_id: str):
    ctx = get_agent().session_manager.load_context_from_file(session_id)
    if ctx is None:
        raise HTTPException(404, "上下文文件不存在")
    return ctx


@router.post("/api/session/auto_title")
async def auto_title(req: AutoTitleRequest):
    agent = get_agent()
    from ..core.database import db_manager, SessionModel
    with db_manager._get_db() as db:
        session = db.query(SessionModel).filter(
            SessionModel.id == req.session_id
        ).first()
        if session and session.title and session.title != "未命名":
            return {"title": session.title}
    title = await agent.generate_title(req.session_id)
    agent.session_manager.rename_session(req.session_id, title)
    return {"title": title}
