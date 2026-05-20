# ══════════════════════════════════════════════════
# core/security.py - 安全管理器
# 功能：控制文件访问和命令执行权限
# 路径：默认白名单包含 SEAI_HOME 和 data
# ══════════════════════════════════════════════════
import os
import re
from pathlib import Path
from typing import List

class SecurityManager:
    DEFAULT_COMMAND_WHITELIST = [
        "echo", "dir", "type", "where", "find", "tree", "date", "time",
        "whoami", "hostname", "systeminfo", "tasklist", "ver",
        "python", "pip", "git", "node", "npm", "npx", "code",
    ]

    def __init__(self, workspace: Path, skills_dir: Path, command_whitelist: List[str] = None):
        self.workspace = workspace.resolve()
        self.skills_dir = skills_dir.resolve()
        self.seai_dir = Path(os.environ.get("SEAI_HOME", str(Path.cwd()))).resolve()
        self.command_whitelist = command_whitelist if command_whitelist is not None else list(self.DEFAULT_COMMAND_WHITELIST)
        self.write_whitelist = [self.workspace, self.skills_dir, self.seai_dir]

    def load_config(self, config: dict):
        security_data = config.get("security", {})
        whitelist_paths = security_data.get("write_whitelist", [])
        self.write_whitelist = [Path(p).resolve() for p in whitelist_paths]
        for default in [self.workspace, self.skills_dir, self.seai_dir]:
            if default not in self.write_whitelist: self.write_whitelist.append(default)
        if "command_whitelist" in security_data: self.command_whitelist = security_data["command_whitelist"]

    def update_whitelist(self, new_list): self.command_whitelist = new_list
    def check_file_access(self, path: str, mode: str = "r") -> bool:
        if mode == "r":
            return True  # 读取操作始终允许
        p = Path(path).resolve()
        for allowed in self.write_whitelist:
            try:
                p.relative_to(allowed)
                return True
            except ValueError:
                pass
        return False
    def check_command(self, command: str) -> bool:
        if not self.command_whitelist: return False
        # 阻止 shell 元字符绕过
        if re.search(r'[;&|`(){}[\]]', command): return False
        # 阻止环境变量展开
        if re.search(r'\$[\w{}]+|%[\w{}]+%', command): return False
        # 阻止 I/O 重定向
        if re.search(r'[<>]', command): return False
        cmd_name = command.strip().split()[0]
        # 命令名本身不能包含路径分隔符（防止执行任意路径）
        if '/' in cmd_name or '\\' in cmd_name: return False
        # 使用 shutil.which 解析实际可执行文件路径，防止 symlink 绕过
        import shutil
        resolved = shutil.which(cmd_name)
        if resolved is None:
            return cmd_name in self.command_whitelist
        return cmd_name in self.command_whitelist
    def scan_plugin_manifest(self, manifest: dict) -> bool:
        return not any(p in ["system","root","kernel"] for p in manifest.get("permissions", []))
    def scan_plugin_code(self, code: str) -> bool:
        return not any(p in code for p in ['eval(','exec(','os.system','subprocess.call','shutil.rmtree'])
    def validate_skill_definition(self, skill_def: dict) -> bool:
        return "name" in skill_def and "command" in skill_def and not any(w in skill_def["command"].lower() for w in ["rm -rf","del /f","format","shutdown"])

    def deep_scan(self, code: str) -> dict:
        """深度静态扫描：在执行前检测代码中的潜在风险"""
        risks = []

        network_patterns = ['requests.', 'httpx.', 'urllib.', 'socket.', 'http.client', 'aiohttp']
        if any(p in code for p in network_patterns):
            risks.append("网络访问")

        delete_patterns = ['os.remove', 'shutil.rmtree', 'os.unlink', 'Path.unlink', 'send2trash']
        if any(p in code for p in delete_patterns):
            risks.append("文件删除")

        system_patterns = ['os.system', 'subprocess.call', 'subprocess.run', 'subprocess.Popen', 'os.popen']
        if any(p in code for p in system_patterns):
            risks.append("系统命令执行")

        eval_patterns = ['eval(', 'exec(', 'compile(', '__import__(']
        if any(p in code for p in eval_patterns):
            risks.append("动态代码执行")

        import_risk = ['import ctypes', 'import winreg', 'import win32api', 'import pyautogui']
        if any(p in code for p in import_risk):
            risks.append("系统级模块导入")

        risk_level = "high" if len(risks) >= 3 else ("medium" if len(risks) >= 1 else "low")

        return {
            "safe": len(risks) == 0,
            "risks": risks,
            "risk_level": risk_level,
            "scanned_at": __import__('time').time()
        }