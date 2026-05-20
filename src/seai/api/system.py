# ══════════════════════════════════════════════════
# api/system.py - System, config, settings & remaining routes
# ────────────────────────────────────────────────
# Covers: config, settings, export, backup (shutil),
# upload, evolution, multi-agent, SEAT, workflow,
# tasks, todos, feedback, system metrics, database,
# knowledge graph, circuit breakers, errors, memory,
# plugins, patches, telegram webhook, terminal ws,
# and MCP endpoints.
# ══════════════════════════════════════════════════
from __future__ import annotations

import json, os, shutil, time, uuid
from datetime import datetime
from pathlib import Path

import psutil
from fastapi import (
    APIRouter, File, HTTPException, Request,
    UploadFile, WebSocket,
)

from loguru import logger

from ..core.config import config_manager
from ..core.database import db_manager, EvolutionLogModel, SessionModel
from ..channels.telegram.receiver import handle_telegram_update
from . import (
    get_agent, get_mcp_server, get_terminal_manager,
)

router = APIRouter()


# ── helpers ───────────────────────────────────────

def _data_dir() -> Path:
    return get_agent().data_dir


def _workspace_dir() -> Path:
    return get_agent().workspace


# ── Config / Settings ─────────────────────────────

@router.post("/api/config")
async def update_api_config(data: dict):
    agent = get_agent()
    config = agent.load_config()
    config.update(data)
    agent.config.save_config()
    return {"status": "ok"}


@router.post("/api/settings")
async def update_settings(data: dict):
    agent = get_agent()
    config = agent.load_config()
    config.update(data)
    agent.config.save_config()
    await agent.reload_config(config)
    return {"status": "ok"}


@router.get("/api/export")
async def export_chat(format: str = "markdown"):
    return {"content": await get_agent().export_current_session(format)}


@router.get("/api/export/log")
async def export_log():
    log_file = config_manager.get_system_config().logs_dir / "seai.log"
    return {
        "content": log_file.read_text(encoding="utf-8") if log_file.exists() else ""
    }


@router.post("/api/settings/webhook")
async def set_webhook(data: dict):
    agent = get_agent()
    config = agent.load_config()
    config["webhook_url"] = data.get("url", "")
    agent.config.save_config()
    return {"status": "ok"}


# ── System backup (shutil) ───────────────────────

@router.post("/api/backup")
async def backup_data():
    data_dir = _data_dir()
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backup_dir / f"backup_{ts}"
    dest.mkdir()
    shutil.copytree(
        Path.cwd(), dest / "SEAI",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "backups*"),
    )
    shutil.copytree(
        data_dir, dest / "data",
        ignore=shutil.ignore_patterns("backups*"),
    )
    return {"path": str(dest)}


# ── Upload ────────────────────────────────────────

@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1] if file.filename else ""
    safe_name = uuid.uuid4().hex + ext
    file_path = _workspace_dir() / safe_name
    with file_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    return {"path": str(file_path)}


# ── Evolution ─────────────────────────────────────

@router.post("/api/evolve")
async def manual_evolve():
    result = await get_agent().evolve()
    return {"content": result}


@router.post("/api/deep_evolve")
async def deep_evolve():
    result = await get_agent().deep_evolve()
    return {"result": result}


@router.get("/api/evo/list")
async def evo_list():
    evo_dir = _data_dir() / "evo"
    if not evo_dir.exists():
        return []
    items = []
    for folder in sorted(
        evo_dir.iterdir(), key=lambda f: f.stat().st_mtime, reverse=True,
    ):
        if folder.is_dir():
            putout = folder / "PUTOUT.md"
            items.append({
                "name": folder.name,
                "putout_exists": putout.exists(),
                "time": folder.stat().st_mtime,
            })
    return items


# ── Multi-Agent ───────────────────────────────────

@router.get("/api/multi_agent/config")
async def get_multi_agent_config():
    return get_agent()._multi_agent_config


@router.post("/api/multi_agent/config")
async def update_multi_agent_config(data: dict):
    agent = get_agent()
    config = agent.load_config()
    ma_config = config.get("multi_agent", {})
    ma_config.update(data)
    config["multi_agent"] = ma_config
    agent.config.save_config()
    agent._multi_agent_config.update(data)
    if "complexity_threshold" in data and agent._complexity_estimator:
        agent._complexity_estimator.threshold = data["complexity_threshold"]
    return {"status": "ok", "config": agent._multi_agent_config}


@router.get("/api/multi_agent/status")
async def get_multi_agent_status():
    agent = get_agent()
    return {
        "config": agent._multi_agent_config,
        "pool_stats": agent._agent_pool.get_stats() if agent._agent_pool else {},
        "complexity_estimator": {
            "threshold": (
                agent._complexity_estimator.threshold
                if agent._complexity_estimator else None
            ),
        },
    }


@router.post("/api/multi_agent/reset")
async def reset_agent_pool():
    agent = get_agent()
    if agent._agent_pool:
        agent._agent_pool.clear_cache()
    return {"status": "ok"}


# ── SEAT ──────────────────────────────────────────

@router.post("/api/seat/submit")
async def seat_submit(data: dict):
    agent = get_agent()
    goal = data.get("goal", "")
    if not goal:
        raise HTTPException(400, "goal 不能为空")
    if not agent._seat_engine:
        raise HTTPException(503, "SEAT 引擎未初始化")
    result = await agent._seat_engine.submit_task(goal, data.get("context"))
    return result


@router.post("/api/seat/cancel")
async def seat_cancel(data: dict):
    agent = get_agent()
    task_id = data.get("task_id", "")
    if not task_id:
        raise HTTPException(400, "task_id 不能为空")
    if not agent._seat_engine:
        raise HTTPException(503, "SEAT 引擎未初始化")
    ok = await agent._seat_engine.cancel_task(task_id)
    return {"status": "cancelled" if ok else "not_found"}


@router.get("/api/seat/task/{task_id}")
async def seat_task_status(task_id: str):
    agent = get_agent()
    if not agent._seat_engine:
        raise HTTPException(503, "SEAT 引擎未初始化")
    task = agent._seat_engine.get_task(task_id)
    if not task:
        raise HTTPException(404, "任务不存在")
    return task


@router.get("/api/seat/tasks")
async def seat_list_tasks():
    agent = get_agent()
    if not agent._seat_engine:
        return {"tasks": []}
    return {"tasks": agent._seat_engine.list_active_tasks()}


@router.get("/api/seat/stats")
async def seat_stats():
    agent = get_agent()
    if not agent._seat_engine:
        return {"initialized": False}
    return agent._seat_engine.get_stats()


# ── Workflow ──────────────────────────────────────

@router.get("/api/workflow/runs")
async def list_workflow_runs():
    agent = get_agent()
    if hasattr(agent, "workflow_engine") and agent.workflow_engine:
        try:
            return agent.workflow_engine.list_runs(limit=50)
        except Exception as e:
            logger.error(f"从引擎读取工作流列表失败: {e}")
    return []


@router.get("/api/workflow/runs/{task_id}")
async def get_workflow_run(task_id: str):
    agent = get_agent()
    run = agent.workflow_engine.get_run_status(task_id)
    if not run:
        raise HTTPException(404, "任务不存在")
    return run


@router.post("/api/workflow/resume")
async def resume_workflow(data: dict):
    result = await get_agent().workflow_engine.resume(
        data["task_id"], data.get("action", "retry"),
        data.get("step_index"), data.get("human_input"),
    )
    return result


@router.post("/api/workflow/{run_id}/retry")
async def retry_workflow_run(run_id: str):
    try:
        agent = get_agent()
        result = await agent.workflow_engine.resume(task_id=run_id, action="retry")
        if result.get("status") == "not_found":
            raise HTTPException(404, "任务不存在")
        return {"status": "success", "message": "任务已重新开始", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"重试工作流任务失败: {e}")
        raise HTTPException(500, f"重试工作流任务失败: {e}")


@router.post("/api/workflow/{run_id}/skip")
async def skip_workflow_step(run_id: str):
    try:
        agent = get_agent()
        result = await agent.workflow_engine.resume(task_id=run_id, action="skip")
        if result.get("status") == "not_found":
            raise HTTPException(404, "任务不存在")
        return {"status": "success", "message": "步骤已跳过", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"跳过工作流步骤失败: {e}")
        raise HTTPException(500, f"跳过工作流步骤失败: {e}")


@router.post("/api/workflow/{run_id}/cancel")
async def cancel_workflow_run(run_id: str):
    try:
        agent = get_agent()
        result = await agent.workflow_engine.resume(task_id=run_id, action="abort")
        if result.get("status") == "not_found":
            raise HTTPException(404, "任务不存在")
        return {"status": "success", "message": "任务已取消", "result": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"取消工作流任务失败: {e}")
        raise HTTPException(500, f"取消工作流任务失败: {e}")


# ── Tasks history ────────────────────────────────

@router.get("/api/tasks/history")
async def task_history():
    history_path = _data_dir() / "task_history.json"
    return (
        json.loads(history_path.read_text())
        if history_path.exists() else []
    )


# ── Todos ─────────────────────────────────────────

def _todo_file() -> Path:
    return _data_dir() / "todos.json"


@router.get("/api/todos")
async def get_todos():
    fp = _todo_file()
    if fp.exists():
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


@router.post("/api/todos/add")
async def add_todo(data: dict):
    fp = _todo_file()
    todos = [] if not fp.exists() else json.loads(fp.read_text())
    todos.append({
        "id": str(uuid.uuid4()),
        "content": data.get("content", ""),
        "time": data.get("time", ""),
        "done": False,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    })
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(todos, f, indent=2, ensure_ascii=False)
    return {"status": "ok"}


@router.put("/api/todos/{todo_id}")
async def update_todo(todo_id: str, data: dict):
    fp = _todo_file()
    if not fp.exists():
        raise HTTPException(404)
    with open(fp, "r", encoding="utf-8") as f:
        todos = json.load(f)
    for t in todos:
        if t["id"] == todo_id:
            t["content"] = data.get("content", t["content"])
            t["time"] = data.get("time", t["time"])
            t["done"] = data.get("done", t["done"])
            break
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(todos, f, indent=2, ensure_ascii=False)
    return {"status": "ok"}


@router.post("/api/todos/delete")
async def delete_todo(data: dict):
    tid = data.get("id", "")
    fp = _todo_file()
    if not tid or not fp.exists():
        return {"status": "error"}
    with open(fp, "r", encoding="utf-8") as f:
        todos = json.load(f)
    todos = [t for t in todos if t["id"] != tid]
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(todos, f, indent=2, ensure_ascii=False)
    return {"status": "ok"}


# ── Feedback ─────────────────────────────────────

def _feedback_file() -> Path:
    return _data_dir() / "feedback.json"


def _evo_feedback_dir() -> Path:
    p = _data_dir() / "evo" / "feedback"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _detail_feedback_dir() -> Path:
    p = _data_dir() / "feedback_detail"
    p.mkdir(parents=True, exist_ok=True)
    return p


@router.post("/api/feedback")
async def feedback(data: dict):
    agent = get_agent()
    fp = _feedback_file()
    feedbacks = [] if not fp.exists() else json.loads(fp.read_text())
    entry = {
        "message_id": data.get("message_id"),
        "rate": data.get("rate"),
        "session_id": agent.session_manager.current_session_id,
        "timestamp": time.time(),
    }
    feedbacks.append(entry)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(feedbacks, f, indent=2)
    evo_file = _evo_feedback_dir() / f"fb_{int(time.time() * 1000)}.json"
    evo_file.write_text(json.dumps(entry, ensure_ascii=False), encoding="utf-8")
    return {"status": "ok"}


@router.post("/api/feedback/detail")
async def feedback_detail(data: dict):
    content = data.get("content", "")
    msg_id = data.get("message_id", "unknown")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = f"feedback_{ts}_{msg_id[:8] if msg_id != 'unknown' else 'direct'}.md"
    file_path = _detail_feedback_dir() / safe_name
    file_path.write_text(content, encoding="utf-8")
    return {"status": "ok", "path": str(file_path)}


# ── System status / metrics ──────────────────────

@router.get("/api/system/status")
async def system_status():
    return {
        "cpu": psutil.cpu_percent(interval=1),
        "memory": psutil.virtual_memory().percent,
        "disk": psutil.disk_usage("C:\\").percent,
        "processes": len(psutil.pids()),
    }


@router.get("/api/system/metrics")
async def get_system_metrics():
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        memory_percent = memory.percent

        system_status_val = "healthy"
        if cpu_percent > 80 or memory_percent > 90:
            system_status_val = "critical"
        elif cpu_percent > 60 or memory_percent > 70:
            system_status_val = "warning"

        token_file = _data_dir() / "token_usage.json"
        total_today = 0
        token_data = []
        if token_file.exists():
            try:
                with open(token_file, "r", encoding="utf-8") as f:
                    token_data = json.load(f)
                today = datetime.now().date().isoformat()
                total_today = sum(
                    entry.get("estimated_tokens", 0)
                    for entry in token_data
                    if entry.get("timestamp", "").startswith(today)
                )
            except Exception:
                pass

        return {
            "system": {
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "memory_used_mb": memory.used / 1024 / 1024,
                "status": system_status_val,
            },
            "tokens": {
                "total_today": total_today,
                "recent_calls": len([
                    entry for entry in token_data
                    if (datetime.fromisoformat(entry["timestamp"]).date()
                        == datetime.now().date())
                ]),
            },
        }
    except Exception as e:
        logger.error(f"获取系统指标失败: {e}")
        raise HTTPException(500, f"获取系统指标失败: {e}")


@router.get("/api/performance")
async def performance():
    agent = get_agent()
    stats = {}
    for s in agent.skill_system.skills:
        stats[s["name"]] = agent.skill_system.get_skill_score(s["name"])
    feedback_count = (
        len(agent._log_tool_feedback_cache)
        if hasattr(agent, "_log_tool_feedback_cache") else 0
    )
    return {"skill_scores": stats, "tool_feedback_count": feedback_count}


# ── Database ──────────────────────────────────────

@router.get("/api/db/stats")
async def db_stats():
    return db_manager.get_stats()


@router.get("/api/db/sessions")
async def db_sessions(username: str = None, limit: int = 50):
    sessions = db_manager.list_sessions(username, limit)
    return {
        "sessions": [
            {
                "id": s.id, "title": s.title,
                "username": s.username,
                "message_count": s.message_count,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
            }
            for s in sessions
        ],
    }


@router.get("/api/db/sessions/{session_id}/messages")
async def db_messages(session_id: str, limit: int = 100):
    messages = db_manager.get_messages(session_id, limit)
    return {
        "messages": [
            {
                "role": m.role, "content": m.content[:500],
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in messages
        ],
    }


@router.get("/api/db/memories")
async def db_search_memories(keyword: str = "", username: str = None, limit: int = 20):
    if not keyword:
        return {"memories": []}
    memories = db_manager.search_memories(keyword, username, limit)
    return {
        "memories": [
            {
                "content": m.content[:300], "mem_type": m.mem_type,
                "importance": m.importance,
                "created_at": m.created_at.isoformat() if m.created_at else None,
            }
            for m in memories
        ],
    }


@router.get("/api/db/evolution")
async def db_evolution_logs(username: str = None, limit: int = 50):
    with db_manager._get_db() as db:
        q = db.query(EvolutionLogModel)
        if username:
            q = q.filter(EvolutionLogModel.username == username)
        logs = q.order_by(EvolutionLogModel.created_at.desc()).limit(limit).all()
        return {
            "logs": [
                {
                    "action": l.action, "description": l.description,
                    "success": l.success, "score": l.score,
                    "created_at": l.created_at.isoformat() if l.created_at else None,
                }
                for l in logs
            ],
        }


# ── Knowledge Graph ──────────────────────────────

def _kg():
    kg = get_agent().knowledge_graph_manager
    if kg is None:
        raise HTTPException(status_code=503, detail="知识图谱未初始化")
    return kg


@router.get("/api/kg/stats")
async def kg_stats():
    return _kg().get_stats()


@router.get("/api/kg/search")
async def kg_search(query: str, depth: int = 2, top_k: int = 10):
    kg = _kg()
    result = kg.search(query, depth, top_k)
    return {"query": query, "context": result, "mode": kg.mode}


@router.get("/api/kg/graph")
async def kg_graph():
    return _kg().get_graph_data()


@router.post("/api/kg/node")
async def kg_add_node(request: Request):
    kg = _kg()
    data = await request.json()
    node_id = kg.add_knowledge(
        text=data.get("text", ""),
        node_type=data.get("type", "concept"),
        importance=data.get("importance", 1.0),
        relations=data.get("relations"),
    )
    return {"node_id": node_id, "mode": kg.mode}


@router.put("/api/kg/node/{node_id}")
async def kg_update_node(node_id: str, request: Request):
    kg = _kg()
    data = await request.json()
    kg.update_knowledge(
        node_id=node_id,
        new_text=data.get("text", ""),
        reason=data.get("reason", "手动更新"),
    )
    return {"status": "ok"}


@router.delete("/api/kg/node/{node_id}")
async def kg_delete_node(node_id: str):
    _kg().delete_knowledge(node_id, reason="手动删除")
    return {"status": "ok"}


@router.get("/api/kg/evolution/{node_id}")
async def kg_evolution(node_id: str, limit: int = 20):
    history = _kg().temporal.get_evolution_history(node_id, limit)
    return {"node_id": node_id, "history": history}


@router.post("/api/kg/snapshot")
async def kg_create_snapshot(request: Request):
    kg = _kg()
    data = await request.json()
    path = kg.create_snapshot(label=data.get("label", ""))
    return {"snapshot_path": path}


@router.get("/api/kg/snapshots")
async def kg_list_snapshots():
    return {"snapshots": _kg().temporal.list_snapshots()}


# ── Circuit breakers ─────────────────────────────

@router.get("/api/circuit_breakers")
async def get_circuit_breakers():
    from ..core.circuit_breaker import breaker_manager
    return breaker_manager.get_all_stats()


@router.post("/api/circuit_breakers/reset")
async def reset_circuit_breakers():
    from ..core.circuit_breaker import breaker_manager
    breaker_manager.reset_all()
    return {"status": "ok"}


# ── Errors ────────────────────────────────────────

@router.get("/api/errors")
async def get_errors():
    agent = get_agent()
    if agent._error_handler:
        return {
            "error_stats": agent._error_handler.error_stats,
            "recent_errors": agent._error_handler.recent_errors[-20:],
            "patterns_count": len(agent._error_handler.error_patterns),
        }
    return {"error_stats": {}, "recent_errors": [], "patterns_count": 0}


# ── Memory graph ──────────────────────────────────

@router.get("/api/memory/graph")
async def memory_graph():
    agent = get_agent()
    nodes, edges = [], []
    if not agent.memory_store or not hasattr(agent.memory_store, "graph"):
        return {"nodes": nodes, "edges": edges}
    for nid, data in agent.memory_store.graph.nodes(data=True):
        nodes.append({
            "id": nid, "text": data.get("text", "")[:100],
            "type": data.get("type", "text"),
            "importance": data.get("importance", 1.0),
        })
    for u, v, data in agent.memory_store.graph.edges(data=True):
        edges.append({
            "source": u, "target": v,
            "relation": data.get("relation", ""),
            "weight": data.get("weight", 1),
        })
    return {"nodes": nodes, "edges": edges}


@router.delete("/api/memory/{node_id}")
async def delete_memory(node_id: str):
    agent = get_agent()
    if not agent.memory_store or not hasattr(agent.memory_store, "graph"):
        return {"status": "not found"}
    if node_id in agent.memory_store.graph.nodes:
        agent.memory_store.graph.remove_node(node_id)
        agent.memory_store._save_graph()
        return {"status": "ok"}
    return {"status": "not found"}


@router.put("/api/memory/{node_id}")
async def update_memory(node_id: str, data: dict):
    agent = get_agent()
    if not agent.memory_store or not hasattr(agent.memory_store, "graph"):
        return {"status": "not found"}
    if node_id in agent.memory_store.graph.nodes:
        agent.memory_store.graph.nodes[node_id]["text"] = data.get("text", "")
        agent.memory_store._save_graph()
        return {"status": "ok"}
    return {"status": "not found"}


# ── Plugins ───────────────────────────────────────

@router.get("/api/plugins/marketplace")
async def marketplace():
    mp_path = _data_dir() / "marketplace.json"
    return json.loads(mp_path.read_text()) if mp_path.exists() else []


@router.get("/api/plugins/installed")
async def installed_plugins():
    agent = get_agent()
    plugins_dir = agent.data_dir / "plugins"
    if not plugins_dir.exists():
        return []
    plugins = []
    for folder in plugins_dir.iterdir():
        if folder.is_dir() and (folder / "plugin.json").exists():
            manifest = json.loads((folder / "plugin.json").read_text())
            plugins.append({
                "name": folder.name,
                "description": manifest.get("description", ""),
                "enabled": True,
            })
    return plugins


@router.post("/api/plugins/uninstall")
async def uninstall_plugin(data: dict):
    agent = get_agent()
    name = data.get("name", "")
    if not name:
        return {"status": "error", "message": "缺少插件名称"}
    plugin_dir = agent.data_dir / "plugins" / name
    if not plugin_dir.exists():
        return {"status": "not_found"}
    shutil.rmtree(plugin_dir)
    await agent.skill_system.load_from_disk()
    agent._refresh_static_prompt()
    return {"status": "ok"}


@router.post("/api/plugins/refresh")
async def refresh_plugins():
    agent = get_agent()
    await agent.skill_system.load_from_disk()
    agent._refresh_static_prompt()
    return {"status": "ok"}


# ── Patches ───────────────────────────────────────

@router.get("/api/patches")
async def list_patches():
    patches_dir = _data_dir() / "patches"
    if not patches_dir.exists():
        patches_dir.mkdir(parents=True, exist_ok=True)
        return []
    patches = []
    for f in sorted(
        patches_dir.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True,
    ):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            patches.append(data)
        except Exception:
            patches.append({"name": f.stem, "error": "读取失败"})
    return patches


@router.post("/api/patches/reload")
async def reload_patches():
    patches_dir = _data_dir() / "patches"
    patches_dir.mkdir(parents=True, exist_ok=True)
    return {"status": "ok", "count": len(list(patches_dir.glob("*.json")))}


# ── Telegram webhook ─────────────────────────────

@router.post("/webhook/telegram")
async def telegram_webhook(req: Request):
    update = await req.json()
    await handle_telegram_update(update, get_agent())
    return {"status": "ok"}


# ── Terminal WebSocket ───────────────────────────

@router.websocket("/ws/terminal")
async def terminal_ws(websocket: WebSocket):
    await get_terminal_manager().connect(websocket)


# ── MCP ──────────────────────────────────────────

@router.get("/api/mcp/tools")
async def mcp_get_tools():
    mcp = get_mcp_server()
    return {"tools": mcp.get_tools()}


@router.post("/api/mcp/call")
async def mcp_call_tool(data: dict):
    mcp = get_mcp_server()
    tool_name = data.get("name", "")
    arguments = data.get("arguments", {})
    if not tool_name:
        raise HTTPException(400, "缺少工具名称")
    result = await mcp.call_tool(tool_name, arguments)
    return {"result": result}
