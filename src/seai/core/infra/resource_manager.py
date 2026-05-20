# ══════════════════════════════════════════════════
# core/resource_manager.py - 热加载管理器
# ══════════════════════════════════════════════════
import os, time, asyncio
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from loguru import logger

class ResourceEventHandler(FileSystemEventHandler):
    def __init__(self, agent): self.agent = agent
    def on_created(self, event):
        if any(event.src_path.endswith(ext) for ext in [".py",".json",".md"]):
            loop = asyncio.get_event_loop()
            loop.create_task(self.agent.skill_system.load_from_disk())
            if hasattr(self.agent, '_refresh_static_prompt'):
                self.agent._refresh_static_prompt()
            logger.info(f"[热加载] 检测到变化：{event.src_path}")

class ResourceManager:
    def __init__(self, agent): self.agent = agent; self.observer = Observer()
    def start_watching(self):
        event_handler = ResourceEventHandler(self.agent)
        for p in [self.agent.data_dir / "plugins", self.agent.data_dir / "skills"]:
            if p.exists(): self.observer.schedule(event_handler, str(p), recursive=True)
        self.observer.start()
    def stop_watching(self): self.observer.stop(); self.observer.join()