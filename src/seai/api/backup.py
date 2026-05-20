# ══════════════════════════════════════════════════
# api/backup.py - GitHub backup endpoints
# ────────────────────────────────────────────────
# GET  /api/backup/config    – get backup config
# POST /api/backup/config    – update backup config
# POST /api/backup/validate  – validate repo path
# POST /api/backup/run       – trigger backup now
# POST /api/backup/export    – export a backup file
# ══════════════════════════════════════════════════
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from scripts.github_backup import (
    load_backup_config,
    save_backup_config,
    validate_repo_path,
    run_backup,
)

from . import get_agent

router = APIRouter()


@router.get("/api/backup/config")
async def get_backup_config():
    return load_backup_config()


@router.post("/api/backup/config")
async def update_backup_config(data: dict):
    current = load_backup_config()
    if "enabled" in data:
        enabled = bool(data["enabled"])
        if enabled:
            repo_url = data.get("repo_url", current.get("repo_url", ""))
            if not repo_url:
                raise HTTPException(
                    status_code=400,
                    detail="请先配置有效的仓库路径，再开启备份功能",
                )
            validation = validate_repo_path(repo_url)
            if not validation["valid"]:
                raise HTTPException(
                    status_code=400,
                    detail=f"仓库路径无效: {validation['error']}",
                )
        current["enabled"] = enabled
    if "repo_url" in data:
        repo_url = data["repo_url"].strip() if data["repo_url"] else ""
        if repo_url:
            validation = validate_repo_path(repo_url)
            if not validation["valid"]:
                raise HTTPException(status_code=400, detail=validation["error"])
            current["repo_url"] = validation["normalized"]
        else:
            current["repo_url"] = ""
    if "github_token" in data:
        current["github_token"] = (
            data["github_token"].strip() if data["github_token"] else ""
        )
    if save_backup_config(current):
        return {"status": "ok", "config": current}
    raise HTTPException(status_code=500, detail="保存配置失败")


@router.post("/api/backup/validate")
async def validate_backup_repo(data: dict):
    repo_url = data.get("repo_url", "")
    return validate_repo_path(repo_url)


@router.post("/api/backup/run")
async def trigger_backup():
    agent = get_agent()
    result = run_backup(data_dir=agent.data_dir)
    if result["success"]:
        return result
    raise HTTPException(status_code=400, detail=result.get("error", "备份失败"))


@router.post("/api/backup/export")
async def export_backup(data: dict = {}):
    backup_path = data.get("path", "")
    if backup_path:
        backup_file = Path(backup_path)
        if backup_file.exists():
            return {"content": backup_file.read_text(encoding="utf-8")}
    return {"content": ""}
