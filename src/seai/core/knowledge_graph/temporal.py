"""时序知识图谱 — 记录知识演变历史"""
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict


class TemporalKnowledgeGraph:
    """时序知识图谱：记录知识演变历史"""

    def __init__(self, persist_dir: Path):
        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._history_path = persist_dir / "knowledge_evolution.jsonl"
        self._snapshots_dir = persist_dir / "knowledge_snapshots"
        self._snapshots_dir.mkdir(parents=True, exist_ok=True)

    def record_evolution(self, node_id: str, action: str, old_text: str = "",
                         new_text: str = "", reason: str = ""):
        entry = {
            "node_id": node_id, "action": action,
            "old_text": old_text[:500], "new_text": new_text[:500],
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        with open(self._history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_evolution_history(self, node_id: str, limit: int = 20) -> List[Dict]:
        history = []
        if not self._history_path.exists():
            return history
        with open(self._history_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("node_id") == node_id:
                        history.append(entry)
                except Exception:
                    pass
        return history[-limit:]

    def create_snapshot(self, label: str = "", graph_data: Dict = None) -> str:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        snapshot_file = self._snapshots_dir / f"snapshot_{timestamp}.json"
        snapshot = {
            "label": label,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "graph_data": graph_data or {}
        }
        snapshot_file.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(snapshot_file)

    def list_snapshots(self) -> List[Dict]:
        snapshots = []
        for f in sorted(self._snapshots_dir.glob("snapshot_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                snapshots.append({"file": f.name, "label": data.get("label", ""), "timestamp": data.get("timestamp", "")})
            except Exception:
                pass
        return snapshots[:50]
