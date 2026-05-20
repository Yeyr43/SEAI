# ══════════════════════════════════════════════════
# core/terminal.py - WebSocket 终端
# 路径：日志文件位于 SEAI_DATA/logs/seai.log
# ══════════════════════════════════════════════════
import asyncio, os, time
from fastapi import WebSocket, WebSocketDisconnect
from pathlib import Path

class TerminalManager:
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        log_path = Path(os.environ.get("SEAI_LOG_FILE", str(Path.cwd().parent / "data" / "logs" / "seai.log")))
        if log_path.exists():
            try:
                await websocket.send_text("\x1b[2J\x1b[H")
                with open(log_path, "r", encoding="utf-8") as f: await websocket.send_text(f.read())
            except Exception:
                pass
        last_size = log_path.stat().st_size if log_path.exists() else 0
        try:
            while True:
                await asyncio.sleep(0.5)
                if not log_path.exists(): continue
                current_size = log_path.stat().st_size
                if current_size > last_size:
                    with open(log_path, "r", encoding="utf-8") as f: f.seek(last_size); await websocket.send_text(f.read())
                    last_size = current_size
                elif current_size < last_size: last_size = 0
        except WebSocketDisconnect:
            pass
        except Exception:
            pass