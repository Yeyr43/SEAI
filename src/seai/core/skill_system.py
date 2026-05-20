# ══════════════════════════════════════════════════
# core/skill_system.py - 技能管理系统（适配接口版本）
# 功能：管理本地技能包，实现 SkillRepository 接口
# ══════════════════════════════════════════════════
import yaml, asyncio, shutil, json, time, os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from .interfaces.skill_repository import SkillRepository
from .error_handler import SmartErrorHandler

ARCHIVE_DIR_NAME = "archived"
VERSION_DIR_NAME = "versions"

class SkillSystem(SkillRepository):
    """技能管理系统（实现 SkillRepository 接口）"""
    
    def __init__(self, skills_dir: Path, error_handler: Optional[SmartErrorHandler] = None):
        self.skills_dir = skills_dir
        self.skills: List[Dict] = []
        self._enabled: Dict[str, bool] = {}
        self.stats_path = skills_dir / "../skill_stats.json"
        self.stats: Dict[str, dict] = {}
        self._error_handler = error_handler
        self._load_stats()

    def _load_stats(self):
        if self.stats_path.exists(): self.stats = json.loads(self.stats_path.read_text(encoding="utf-8"))
        else: self.stats = {}
    def _save_stats(self):
        self.stats_path.write_text(json.dumps(self.stats, indent=2, ensure_ascii=False), encoding="utf-8")
    def record_skill_use(self, name: str, success: bool):
        if name not in self.stats: self.stats[name] = {"total":0,"success":0,"last_used":0,"consecutive_failures":0}
        self.stats[name]["total"] += 1
        if success: self.stats[name]["success"] += 1; self.stats[name]["consecutive_failures"] = 0
        else: self.stats[name]["consecutive_failures"] = self.stats[name].get("consecutive_failures",0) + 1
        self.stats[name]["last_used"] = time.time()
        self._save_stats()
    def get_skill_score(self, name: str) -> float:
        if name not in self.stats: return 0.5
        s = self.stats[name]; total = s.get("total",0)
        if total == 0: return 0.5
        success_rate = s.get("success",0) / total
        frequency_score = min(total / 10, 1.0)
        return 0.7 * success_rate + 0.3 * frequency_score

    async def load_from_disk(self):
        self.skills.clear()
        if not self.skills_dir.exists(): return
        for md in self.skills_dir.rglob("SKILL.md"):
            skill = self._parse(md)
            if skill:
                self.skills.append(skill)
                if skill["name"] not in self._enabled: self._enabled[skill["name"]] = True

    def _parse(self, path: Path) -> Optional[Dict]:
        try:
            content = path.read_text(encoding="utf-8")
            if not content.startswith("---"): return None
            parts = content.split("---",2)
            if len(parts) < 3: return None
            meta = yaml.safe_load(parts[1]); meta["sop"] = parts[2].strip(); meta["name"] = path.parent.name
            return meta
        except Exception:
            return None

    def is_enabled(self, name): return self._enabled.get(name, True)
    def set_enabled(self, name, val): self._enabled[name] = val
    def apply_enabled_map(self, m): self._enabled.update(m)
    def get_all_skills(self) -> List[Dict]:
        return [{**s, "enabled": self.is_enabled(s["name"]), "score": self.get_skill_score(s["name"])} for s in self.skills]

    async def execute_skill(self, name, args, security=None) -> str:
        if not self.is_enabled(name): return f"技能 {name} 已禁用"
        for s in self.skills:
            if s["name"] == name:
                cmd = s.get("command", "")
                if not cmd: return f"技能 {name} 无命令"
                inp = args.get("input", ""); cmd = cmd.replace("{input}", inp)
                executable = cmd.split()[0]
                import shutil
                if shutil.which(executable) is None:
                    self.record_skill_use(name, False)
                    err_msg = f"技能脚本未找到：{executable}"
                    if self._error_handler:
                        diagnosis = self._error_handler.handle_error(
                            FileNotFoundError(f"可执行文件未找到: {executable}"),
                            {"skill": name, "command": cmd}
                        )
                        err_msg = f"{err_msg}。建议: {diagnosis.immediate_fix}"
                    return err_msg
                if security and not security.check_command(cmd):
                    self.record_skill_use(name, False); return f"命令 {cmd} 被拒绝"
                if s.get("sandbox", False):
                    from .sandbox import SandboxExecutor
                    sandbox = SandboxExecutor(self.skills_dir)
                    try:
                        stdout, stderr, code = await sandbox.execute(cmd, timeout=30)
                        success = code == 0
                        self.record_skill_use(name, success)
                        return stdout if success else f"沙箱执行失败：{stderr}"
                    except TimeoutError as e:
                        self.record_skill_use(name, False)
                        if self._error_handler:
                            diagnosis = self._error_handler.handle_error(e, {"skill": name, "command": cmd})
                            return f"技能执行超时: {diagnosis.immediate_fix}"
                        return f"技能执行超时: {str(e)}"
                try:
                    proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
                    stdout, stderr = await proc.communicate()
                    success = proc.returncode == 0
                    self.record_skill_use(name, success)
                    return stdout.decode() if success else f"执行失败：{stderr.decode()}"
                except FileNotFoundError as e:
                    self.record_skill_use(name, False)
                    if self._error_handler:
                        diagnosis = self._error_handler.handle_error(e, {"skill": name, "command": cmd})
                        return f"文件未找到: {diagnosis.immediate_fix}"
                    return f"异常：{e}"
                except PermissionError as e:
                    self.record_skill_use(name, False)
                    if self._error_handler:
                        diagnosis = self._error_handler.handle_error(e, {"skill": name, "command": cmd})
                        return f"权限不足: {diagnosis.immediate_fix}"
                    return f"异常：{e}"
                except Exception as e:
                    self.record_skill_use(name, False)
                    if self._error_handler:
                        diagnosis = self._error_handler.handle_error(e, {"skill": name, "command": cmd})
                        return f"技能异常 [{diagnosis.error_type}]: {diagnosis.immediate_fix}"
                    return f"异常：{e}"
        return f"技能 {name} 未找到"

    def archive_skill(self, name: str) -> bool:
        skill_dir = self.skills_dir / name
        if not skill_dir.exists():
            return False
        archive_dir = self.skills_dir / ARCHIVE_DIR_NAME / name
        archive_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(skill_dir), str(archive_dir))
        self.skills = [s for s in self.skills if s["name"] != name]
        self._enabled.pop(name, None)
        if name in self.stats:
            self.stats[name]["archived"] = True
            self.stats[name]["archived_at"] = time.time()
        self._save_stats()
        return True

    def get_archived_skills(self) -> list:
        archive_dir = self.skills_dir / ARCHIVE_DIR_NAME
        if not archive_dir.exists():
            return []
        return [d.name for d in archive_dir.iterdir() if d.is_dir()]

    def restore_skill(self, name: str) -> bool:
        archive_dir = self.skills_dir / ARCHIVE_DIR_NAME / name
        if not archive_dir.exists():
            return False
        target_dir = self.skills_dir / name
        shutil.move(str(archive_dir), str(target_dir))
        if name in self.stats:
            self.stats[name].pop("archived", None)
            self.stats[name].pop("archived_at", None)
        self._save_stats()
        asyncio.create_task(self.load_from_disk())
        return True

    def save_skill_version(self, name: str):
        skill_dir = self.skills_dir / name
        if not skill_dir.exists():
            return
        version_dir = self.skills_dir / VERSION_DIR_NAME / name
        version_dir.mkdir(parents=True, exist_ok=True)
        version_name = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copytree(skill_dir, version_dir / version_name)
        versions = sorted([d.name for d in version_dir.iterdir()], reverse=True)
        if len(versions) > 10:
            for old in versions[10:]:
                shutil.rmtree(version_dir / old, ignore_errors=True)

    def rollback_skill(self, name: str, version: str = None) -> bool:
        version_dir = self.skills_dir / VERSION_DIR_NAME / name
        if not version_dir.exists():
            return False
        versions = sorted([d.name for d in version_dir.iterdir()], reverse=True)
        if not versions:
            return False
        target = version if version and version in versions else versions[0]
        skill_dir = self.skills_dir / name
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        shutil.copytree(version_dir / target, skill_dir)
        asyncio.create_task(self.load_from_disk())
        return True

    def delete_skill(self, name):
        self.skills = [s for s in self.skills if s["name"] != name]
        self._enabled.pop(name, None)
        (self.skills_dir / name).exists() and shutil.rmtree(self.skills_dir / name, ignore_errors=True)

    async def load_skills(self):
        await self.load_from_disk()

    def is_skill_enabled(self, name: str) -> bool:
        return self.is_enabled(name)

    def set_skill_enabled(self, name: str, enabled: bool):
        self.set_enabled(name, enabled)

    def record_skill_usage(self, name: str, success: bool):
        self.record_skill_use(name, success)

    def create_skill(self, skill_data: Dict) -> bool:
        name = skill_data.get("name", "")
        if not name:
            return False
        skill_dir = self.skills_dir / name
        skill_dir.mkdir(parents=True, exist_ok=True)
        md_path = skill_dir / "SKILL.md"
        md_path.write_text(skill_data.get("content", ""), encoding="utf-8")
        self._enabled[name] = True
        return True