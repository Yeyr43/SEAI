# ══════════════════════════════════════════════════
# api/logs.py - Log streaming & export
# ────────────────────────────────────────────────
# GET  /api/logs/stream   – SSE stream of log file
# POST /api/logs/export   – export full log content
# ══════════════════════════════════════════════════
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..core.config import config_manager

router = APIRouter()


def _logs_dir() -> Path:
    return config_manager.get_system_config().logs_dir


@router.get("/api/logs/stream")
async def logs_stream():
    log_file = _logs_dir() / "seai.log"

    def log_generator():
        if log_file.exists():
            with open(log_file, "r", encoding="utf-8") as f:
                yield f.read()
        last_size = log_file.stat().st_size if log_file.exists() else 0
        while True:
            time.sleep(0.5)
            if not log_file.exists():
                continue
            current_size = log_file.stat().st_size
            if current_size > last_size:
                with open(log_file, "r", encoding="utf-8") as f:
                    f.seek(last_size)
                    yield f.read()
                last_size = current_size
            elif current_size < last_size:
                last_size = 0

    return StreamingResponse(log_generator(), media_type="text/plain")


@router.post("/api/logs/export")
async def export_logs(data: dict = {}):
    log_file = _logs_dir() / "seai.log"
    content = (
        log_file.read_text(encoding="utf-8", errors="replace")
        if log_file.exists()
        else ""
    )
    return {"content": content}
