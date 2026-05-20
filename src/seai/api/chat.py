# ══════════════════════════════════════════════════
# api/chat.py - Chat endpoints
# ────────────────────────────────────────────────
# POST /api/chat            – send message (SSE or plain)
# POST /api/stop            – stop active requests
# POST /api/chat/image      – chat with uploaded image
# POST /api/debug           – run a shell command
# POST /api/fetch_web       – proxy fetch a URL
# ══════════════════════════════════════════════════
from __future__ import annotations

import asyncio, json, os, uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from loguru import logger

from ..core.handler.auth_handler import verify_api_key
from . import get_agent

router = APIRouter()


# ── Models ────────────────────────────────────────

class ChatRequest(BaseModel):
    query: str
    stream: bool = True
    thinking_enabled: bool = True
    web_search: bool = False
    session_id: str = ""


class DebugRequest(BaseModel):
    command: str


class FetchWebRequest(BaseModel):
    url: str


# ── Chat ──────────────────────────────────────────

@router.post("/api/chat")
async def chat(req: ChatRequest, _: bool = Depends(verify_api_key)):
    try:
        agent = get_agent()
        if req.stream:
            async def sse_wrapper():
                async for chunk in agent.chat_stream(
                    req.query, thinking_enabled=req.thinking_enabled,
                    web_search=req.web_search, session_id=req.session_id,
                ):
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps('[DONE]')}\n\n"
            return StreamingResponse(sse_wrapper(), media_type="text/event-stream")
        else:
            reply = await agent.chat(
                req.query, thinking_enabled=req.thinking_enabled,
                web_search=req.web_search, session_id=req.session_id,
            )
            return {"reply": reply}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/stop")
async def stop():
    await get_agent().stop_active_requests()
    return {"status": "stopped"}


# ── Chat with image ───────────────────────────────

_SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
    ".wav", ".mp3", ".ogg", ".flac", ".m4a",
}

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}


@router.post("/api/chat/image")
async def chat_with_image(
    query: str = Form(...),
    file: UploadFile = File(...),
    stream: bool = Form(True),
    session_id: str = Form(""),
    thinking_enabled: bool = Form(True),
    web_search: bool = Form(False),
    _: bool = Depends(verify_api_key),
):
    try:
        agent = get_agent()
        ext = os.path.splitext(file.filename)[1] if file.filename else ".jpg"
        safe_name = f"upload_{uuid.uuid4().hex}{ext}"
        file_path = agent.workspace / safe_name
        with open(file_path, "wb") as f:
            f.write(await file.read())

        if ext.lower() not in _SUPPORTED_EXTENSIONS:
            full_query = query
        elif ext.lower() in _IMAGE_EXTENSIONS:
            full_query = f'{query}\n图片: "{file_path}"'
        else:
            full_query = f'{query}\n音频: "{file_path}"'

        if stream:
            async def _sse():
                async for chunk in agent.chat_stream(
                    full_query, thinking_enabled=thinking_enabled,
                    web_search=web_search, session_id=session_id,
                ):
                    yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps('[DONE]')}\n\n"
            return StreamingResponse(_sse(), media_type="text/event-stream")
        else:
            reply = await agent.chat(
                full_query, thinking_enabled=thinking_enabled,
                web_search=web_search, session_id=session_id,
            )
            return {"reply": reply}
    except Exception as e:
        logger.error(f"图片对话失败: {e}")
        raise HTTPException(500, f"图片对话失败: {e}")


# ── Debug / FetchWeb ──────────────────────────────

@router.post("/api/debug")
async def debug(req: DebugRequest):
    agent = get_agent()
    if not agent.security.check_command(req.command):
        return {"result": "命令被拒绝"}
    try:
        proc = await asyncio.create_subprocess_shell(
            req.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(agent.workspace),
        )
        stdout, stderr = await proc.communicate()
        return {
            "result": stdout.decode()
            if proc.returncode == 0
            else f"错误:\n{stderr.decode()}"
        }
    except Exception as e:
        return {"result": str(e)}


@router.post("/api/fetch_web")
async def fetch_web(req: FetchWebRequest):
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(req.url)
            resp.raise_for_status()
            return {"content": resp.text[:5000], "status": resp.status_code}
    except Exception as e:
        return {"content": str(e), "status": 0}
