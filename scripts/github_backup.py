#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SEAI GitHub 备份脚本
支持手动开关和自定义仓库路径配置
"""
import os
import re
import json
import subprocess
import shutil
import tempfile
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("seai.backup")

def _get_data_dir() -> Path:
    from pathlib import Path
    import os
    project_se_data = Path(__file__).parent.parent / "data"
    return Path(os.environ.get("SEAI_DATA", str(project_se_data)))

DATA_DIR = _get_data_dir()
BACKUP_CONFIG_PATH = DATA_DIR / "backup_config.json"

DEFAULT_CONFIG = {
    "enabled": False,
    "repo_url": "",
    "github_token": "",
    "last_backup": None,
    "last_status": None,
}

GITHUB_REPO_PATTERN = re.compile(
    r"^https://github\.com/[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+(?:\.git)?$"
)


def load_backup_config() -> dict:
    if BACKUP_CONFIG_PATH.exists():
        try:
            with open(BACKUP_CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
            return {**DEFAULT_CONFIG, **config}
        except (json.JSONDecodeError, IOError):
            logger.warning("备份配置文件损坏，使用默认配置")
    return dict(DEFAULT_CONFIG)


def save_backup_config(config: dict) -> bool:
    try:
        BACKUP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(BACKUP_CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        return True
    except IOError as e:
        logger.error(f"保存备份配置失败: {e}")
        return False


def validate_repo_path(repo_url: str) -> dict:
    if not repo_url or not repo_url.strip():
        return {"valid": False, "error": "仓库路径不能为空"}

    repo_url = repo_url.strip()

    if not GITHUB_REPO_PATTERN.match(repo_url):
        return {
            "valid": False,
            "error": "仓库路径格式无效，应为 https://github.com/用户名/仓库名",
        }

    if not repo_url.endswith(".git"):
        repo_url += ".git"

    return {"valid": True, "normalized": repo_url}


def run_backup(repo_url: str = None, github_token: str = None, data_dir: Path = None) -> dict:
    config = load_backup_config()

    if not config.get("enabled", False):
        return {"success": False, "error": "备份功能未启用，请在设置中开启"}

    repo = repo_url or config.get("repo_url", "")
    token = github_token or config.get("github_token", "") or os.environ.get("SEAI_GITHUB_TOKEN", "")

    if not repo:
        return {"success": False, "error": "未设置备份仓库路径"}

    if not token:
        return {"success": False, "error": "未设置 GitHub Token，请设置 SEAI_GITHUB_TOKEN 环境变量或在配置中填写"}

    validation = validate_repo_path(repo)
    if not validation["valid"]:
        return {"success": False, "error": validation["error"]}

    repo = validation["normalized"]

    actual_data_dir = data_dir or DATA_DIR

    temp_dir = Path(tempfile.mkdtemp(prefix="seai_backup_"))
    try:
        memory_dir = actual_data_dir / "memory"
        skills_dir = actual_data_dir / "skills"
        config_file = actual_data_dir / "config.json"
        profile_file = actual_data_dir / "user_profile.md"

        if memory_dir.exists():
            shutil.copytree(memory_dir, temp_dir / "memory", dirs_exist_ok=True)
        if skills_dir.exists():
            shutil.copytree(skills_dir, temp_dir / "skills", dirs_exist_ok=True)
        if config_file.exists():
            shutil.copy(config_file, temp_dir / "config.json")
        if profile_file.exists():
            shutil.copy(profile_file, temp_dir / "user_profile.md")

        os.chdir(temp_dir)
        subprocess.run(["git", "init"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "seai@localhost"], check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "SEAI Backup"], check=True, capture_output=True)
        subprocess.run(["git", "add", "."], check=True, capture_output=True)

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        subprocess.run(["git", "commit", "-m", f"Auto backup {ts}"], check=True, capture_output=True)

        remote_url = repo.replace("https://", f"https://{token}@")
        subprocess.run(["git", "push", remote_url, "main", "--force"], check=True, capture_output=True)

        config["last_backup"] = ts
        config["last_status"] = "success"
        save_backup_config(config)

        logger.info(f"备份成功：{ts}")
        return {"success": True, "message": f"备份成功：{ts}", "timestamp": ts}
    except subprocess.CalledProcessError as e:
        error_msg = f"Git 操作失败：{e.stderr.decode() if e.stderr else str(e)}"
        config["last_status"] = "failed"
        save_backup_config(config)
        logger.error(error_msg)
        return {"success": False, "error": error_msg}
    except Exception as e:
        error_msg = f"备份失败：{e}"
        config["last_status"] = "failed"
        save_backup_config(config)
        logger.error(error_msg)
        return {"success": False, "error": error_msg}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    result = run_backup()
    print(json.dumps(result, ensure_ascii=False, indent=2))