# ══════════════════════════════════════════════════
# app.py - SEAI Web 服务入口
# ────────────────────────────────────────────────
# 功能：FastAPI 应用主入口，管理所有 HTTP/WebSocket 路由、
#       后台调度器、文件上传、技能/模型/会话/备份/进化等 API。
#       同时挂载 www/ 目录作为前端静态文件。
# 路径：SEAI 源码目录为 SEAI_HOME 或当前目录
#       data 数据目录为 SEAI_DATA 或 ../data
# ══════════════════════════════════════════════════
import sys, os, asyncio, json, shutil, uuid, time
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, WebSocket, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from loguru import logger
from seai.core.agent import SEAgent
from seai.core.terminal import TerminalManager
from seai.core.resource_manager import ResourceManager
from seai.core.config import config_manager
from seai.core.database import init_db, db_manager, EvolutionLogModel
from seai.core.service.health_service import HealthService
from seai.core.service.auth_service import AuthService
from seai.core.handler.health_handler import router as health_router, init_health_handler
from seai.core.handler.auth_handler import (
    init_auth_handler, verify_api_key, auth_middleware, rate_limit_middleware
)
from seai.channels.telegram.receiver import handle_telegram_update
from seai.utils.logger import setup_logger
from seai.mcp_server import SEAIMCPServer
from seai.api import set_agent, set_terminal_manager, set_mcp_server, create_api_router


startup_time = time.time()

system_config = config_manager.get_system_config()
DATA_DIR = system_config.data_dir
WORKSPACE_DIR = system_config.workspace_dir
LOGS_DIR = system_config.logs_dir

for d in [DATA_DIR, WORKSPACE_DIR, LOGS_DIR]:
    d.mkdir(parents=True, exist_ok=True)

setup_logger(LOGS_DIR)
agent: SEAgent = None
terminal_manager = TerminalManager()
resource_manager: ResourceManager = None
knowledge_graph_manager: KnowledgeGraphManager = None
health_service = HealthService()
auth_service = AuthService(config_manager)

async def schedule_loop(agent: SEAgent):
    """后台调度器：每分钟检查并执行定时任务和待办提醒（非阻塞 I/O）"""
    loop = asyncio.get_event_loop()
    while True:
        try:
            now = datetime.now().strftime("%H:%M")
            # 定时任务执行（使用线程池避免阻塞事件循环）
            tasks = []
            if agent.schedule_path.exists():
                tasks = await loop.run_in_executor(None, _load_json, agent.schedule_path)

            for task in tasks:
                if task.get("time") == now:
                    cmd = task["command"]
                    logger.info(f"执行定时任务：{cmd}")
                    try:
                        proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=str(agent.workspace))
                        stdout, stderr = await proc.communicate()
                        output = stdout.decode() + "\n" + stderr.decode()
                    except Exception as e:
                        output = str(e)
                    out_file = agent.scheduled_outputs_dir / f"output_{task['time'].replace(':','_')}.txt"
                    await loop.run_in_executor(None, lambda: out_file.write_text(f"[{datetime.now()}] 执行：{cmd}\n{output}\n", encoding="utf-8"))
                    if agent.session_manager.current_session_id:
                        agent.session_manager.add_message("system", f"定时任务 {task['time']} 执行完毕：\n{output[:200]}")
            # 待办提醒
            todo_path = DATA_DIR / "todos.json"
            todos = await loop.run_in_executor(None, _load_json, todo_path) if todo_path.exists() else []
            for todo in todos:
                if todo.get("time") == now and not todo.get("done"):
                    cmd = todo.get("content", "")
                    logger.info(f"执行待办：{cmd}")
                    if agent.session_manager.current_session_id:
                        agent.session_manager.add_message("system", f"⏰ 待办提醒：{cmd}")
                    todo["done"] = True
            if todos:
                await loop.run_in_executor(None, _dump_json, todo_path, todos)
            await asyncio.sleep(60)
        except Exception as e:
            logger.error(f"调度器异常：{e}")
            await asyncio.sleep(60)


def _load_json(path: Path) -> list:
    """线程池中执行的同步 JSON 加载"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _dump_json(path: Path, data: list):
    """线程池中执行的同步 JSON 保存"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动智能体、资源监听和后台调度；关闭时清理"""
    global agent, resource_manager, knowledge_graph_manager, mcp_server
    agent = SEAgent()
    await agent.initialize()
    knowledge_graph_manager = agent.knowledge_graph_manager
    mcp_server = SEAIMCPServer(agent)
    set_agent(agent)
    set_terminal_manager(terminal_manager)
    set_mcp_server(mcp_server)

    init_db()
    health_service.set_agent(agent)
    init_health_handler(health_service)
    init_auth_handler(auth_service)
    resource_manager = ResourceManager(agent)
    resource_manager.start_watching()
    schedule_task = asyncio.create_task(schedule_loop(agent))
    yield
    schedule_task.cancel()
    resource_manager.stop_watching()
    await agent.shutdown()

app = FastAPI(title="SEAI", lifespan=lifespan)

# CORS 配置（优先从配置读取，默认限制为 localhost）
cors_origins = system_config.allowed_origins if hasattr(system_config, 'allowed_origins') and system_config.allowed_origins else ["http://localhost:8080", "http://127.0.0.1:8080"]
app.add_middleware(CORSMiddleware, allow_origins=cors_origins, allow_methods=["*"], allow_headers=["*"])
app.middleware("http")(auth_middleware)
app.middleware("http")(rate_limit_middleware)
app.include_router(health_router)
app.include_router(create_api_router())

# TypeScript 前端优先，回退到原始 www/
www_dist_path = Path(__file__).parent.parent.parent / "www_dist"
www_path = Path(__file__).parent.parent.parent / "www"
if www_dist_path.exists():
    app.mount("/", StaticFiles(directory=str(www_dist_path), html=True), name="www_dist")
elif www_path.exists():
    app.mount("/", StaticFiles(directory=str(www_path), html=True), name="www")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SEAI 服务")
    parser.add_argument("--server", action="store_true", help="以服务器模式启动（仅监听本地）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--port", type=int, default=8080, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="启用热重载")
    args = parser.parse_args()

    if args.server:
        import uvicorn
        uvicorn.run("app:app", host=args.host, port=args.port, reload=args.reload)
    else:
        from seai_window import main as window_main
        window_main()