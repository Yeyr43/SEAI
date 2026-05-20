"""
记忆数据仓库
封装记忆相关的数据持久化操作
"""
from pathlib import Path
from typing import List, Dict, Optional
import json
from .base import BaseRepository


class MemoryRepository(BaseRepository[Dict]):
    def __init__(self, data_dir: Path):
        super().__init__()
        self.data_dir = data_dir
        self.memory_dir = data_dir / "memory"
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def get_long_term_memories(self, limit: int = 100) -> List[Dict]:
        path = self.memory_dir / "long_term.jsonl"
        memories = []
        if not path.exists():
            return memories
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        memories.append(json.loads(line))
        except Exception:
            pass
        return memories[-limit:]

    def add_long_term_memory(self, entry: Dict) -> bool:
        path = self.memory_dir / "long_term.jsonl"
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            return True
        except Exception:
            return False

    def get_user_profile(self) -> str:
        path = self.memory_dir / "user_profile.md"
        return self._read_text(path)

    def update_user_profile(self, content: str) -> bool:
        path = self.memory_dir / "user_profile.md"
        return self._write_text(path, content)

    def get_global_knowledge(self) -> str:
        path = self.memory_dir / "global_knowledge.md"
        return self._read_text(path)

    def update_global_knowledge(self, content: str) -> bool:
        path = self.memory_dir / "global_knowledge.md"
        return self._write_text(path, content)

    def archive_memories(self, days: int = 30) -> int:
        import time
        path = self.memory_dir / "long_term.jsonl"
        archive_path = self.memory_dir / "long_term_archive.jsonl"
        if not path.exists():
            return 0
        cutoff = time.time() - days * 86400
        active = []
        archived = 0
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    entry = json.loads(line)
                    if entry.get("last_access", 0) < cutoff:
                        with open(archive_path, "a", encoding="utf-8") as af:
                            af.write(json.dumps(entry, ensure_ascii=False) + "\n")
                        archived += 1
                    else:
                        active.append(entry)
            with open(path, "w", encoding="utf-8") as f:
                for entry in active:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass
        return archived