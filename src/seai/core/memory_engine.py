# ══════════════════════════════════════════════════
# core/memory_engine.py - 多层记忆引擎（适配接口版本）
# 功能：管理智能体的四层记忆体系，实现 MemoryStore 接口
# ══════════════════════════════════════════════════
import os, uuid, time, json, re
from pathlib import Path
from typing import List, Optional, Dict
from datetime import datetime, timedelta
import chromadb
import networkx as nx
from loguru import logger
from .interfaces.memory_store import MemoryStore

class MemoryEngine(MemoryStore):
    """多层记忆引擎（实现 MemoryStore 接口）"""

    def __init__(self, persist_dir: Path, llm_manager=None):
        persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(persist_dir))
        self.embed_fn = self._load_embedding_model()
        self.collection = self.client.get_or_create_collection(name="memories", embedding_function=self.embed_fn)
        self.long_term_path = persist_dir / "long_term.jsonl"
        self.user_profile_path = persist_dir / "user_profile.md"
        self.global_knowledge_path = persist_dir / "global_knowledge.md"
        self.graph_path = persist_dir / "memory_graph.json"
        self.archive_path = persist_dir / "long_term_archive.jsonl"
        self.media_dir = persist_dir / "media"
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.llm_manager = llm_manager
        for p in [self.long_term_path, self.user_profile_path, self.global_knowledge_path, self.archive_path]:
            if not p.exists(): p.write_text("", encoding="utf-8")

        # 自动迁移 pickle → JSON
        _old_pkl = persist_dir / "memory_graph.pkl"
        if _old_pkl.exists() and not self.graph_path.exists():
            try:
                import pickle as _pk
                self.graph = _pk.load(open(_old_pkl, "rb"))
                self._save_graph()
                _old_pkl.unlink()
                logger.info("Migrated memory graph from pickle to JSON")
            except Exception as exc:
                logger.warning("Pickle graph migration failed: {}", exc)
                self.graph = nx.Graph()
        elif self.graph_path.exists():
            try:
                data = json.loads(self.graph_path.read_text(encoding="utf-8"))
                self.graph = nx.node_link_graph(data)
            except Exception as exc:
                logger.warning("Failed to load graph from {}: {}", self.graph_path, exc)
                self.graph = nx.Graph()
        else:
            self.graph = nx.Graph()

    def _save_graph(self):
        data = nx.node_link_data(self.graph)
        self.graph_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def _load_embedding_model(self):
        from .model_downloader import load_embedding_model

        def progress_callback(stage, message):
            if stage in ("cache_hit", "success", "fallback_local", "partial_ok"):
                print(f"[SEAI] {message}")
            elif stage in ("error", "timeout", "network_error"):
                print(f"[SEAI] 警告: {message}")
            else:
                print(f"[SEAI] {message}")

        return load_embedding_model(progress_callback=progress_callback)

    def add_memory(self, content: str, priority: int = 1):
        self.collection.add(documents=[content], metadatas=[{"priority":priority,"timestamp":time.time()}], ids=[uuid.uuid4().hex])

    def search_memory(self, query: str, top_k: int = 5) -> List[str]:
        return self.search(query, top_k)

    def add_long_term_memory(self, summary: str, relations: Dict = None, mem_type: str = "text") -> str:
        return self.add_long_term_memory_with_links(summary, relations, mem_type)

    def get_recent_memories(self, limit: int = 10) -> List[Dict]:
        lines = []
        if self.long_term_path.exists():
            with open(self.long_term_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        recent = lines[-limit:]
        result = []
        for line in recent:
            try:
                entry = json.loads(line)
                result.append(entry)
            except Exception:
                pass
        return result

    def get_context_for_query(self, query: str, depth: int = 2) -> str:
        return self.get_graph_context(query, depth)

    def archive_old_memories(self):
        self.archive_low_weight_memories()
    def search(self, query: str, top_k: int = 5, mem_types: list = None, search_mode: str = "semantic") -> List[str]:
        if search_mode == "text":
            return self._text_search(query, top_k, mem_types)
        elif search_mode == "hybrid":
            semantic_results = self._semantic_search(query, max(top_k // 2, 1), mem_types)
            text_results = self._text_search(query, max(top_k // 2, 1), mem_types)
            return self._merge_results(semantic_results, text_results, top_k)
        else:
            results = self._semantic_search(query, top_k, mem_types)
            if len(results) < top_k:
                text_results = self._text_search(query, top_k - len(results), mem_types)
                results = self._merge_results(results, text_results, top_k)
            return results

    def search_by_type(self, query: str, mem_types: List[str], top_k: int = 5) -> List[Dict]:
        """类型感知检索：按记忆类型筛选搜索结果"""
        results = []
        if not self.long_term_path.exists():
            return results
        with open(self.long_term_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if entry.get("type") in mem_types:
                        results.append(entry)
                except Exception:
                    pass
        query_lower = query.lower()
        scored = []
        for entry in results:
            text = entry.get("text", "")
            score = sum(1 for word in query_lower.split() if word in text.lower())
            scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [entry for _, entry in scored[:top_k]]

    def get_memories_by_timerange(
        self,
        start_time: str = None,
        end_time: str = None,
        mem_types: List[str] = None,
        limit: int = 20
    ) -> List[Dict]:
        """按时间范围检索记忆"""
        results = []
        if not self.long_term_path.exists():
            return results
        with open(self.long_term_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    memory = json.loads(line)
                    ts = memory.get("timestamp", "")
                    if not ts:
                        continue
                    if start_time and ts < start_time:
                        continue
                    if end_time and ts > end_time:
                        continue
                    if mem_types and memory.get("type") not in mem_types:
                        continue
                    results.append(memory)
                    if len(results) >= limit:
                        break
                except Exception:
                    pass
        return results

    def add_long_term_memory_with_links(self, summary: str, relations: dict = None, mem_type: str = "text", storage_mode: str = "auto", media_id: str = None):
        if storage_mode == "auto":
            if mem_type in ("code", "error", "file_snapshot", "exact"):
                storage_mode = "original"
            else:
                storage_mode = "summary"
        node_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().isoformat()
        entry = {"id": node_id, "text": summary, "type": mem_type, "importance": 1.0, "created_at": time.time(), "last_access": time.time(), "access_count": 0, "timestamp": timestamp, "storage_mode": storage_mode, "related_todos": []}
        if media_id:
            entry["media_id"] = media_id
        with open(self.long_term_path, "a", encoding="utf-8") as f: f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self.graph.add_node(node_id, text=summary, type=mem_type, importance=1.0, access_count=0, last_access=time.time(), timestamp=timestamp)
        if relations:
            for target_id, rel_type in relations.items():
                if target_id in self.graph.nodes:
                    weight = 3 if rel_type == "similar" else (2 if rel_type == "cause" else 1)
                    self.graph.add_edge(node_id, target_id, relation=rel_type, weight=weight)
        entities = self._extract_entities(summary)
        for existing in self.graph.nodes:
            if existing == node_id: continue
            common = set(entities) & set(self.graph.nodes[existing].get("entities", []))
            if common: self.graph.add_edge(node_id, existing, weight=len(common))
        self._save_graph()

    def _extract_entities(self, text: str) -> list:
        """从文本中提取实体（函数名、类名、技术术语、专有名词等）"""
        import re as _re
        entities = set()
        # 大写开头的词（ProperNoun）
        entities.update(_re.findall(r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)*\b', text))
        # 数字实体
        entities.update(_re.findall(r'\b[0-9]+\.[0-9]+|[0-9]+\b', text))
        # 技术关键词
        tech_keywords = {'Python', 'FastAPI', 'Windows', 'Linux', 'API', 'JSON', 'SQLite',
                         'ChromaDB', 'Docker', 'Grafana', 'React', 'TypeScript', 'JavaScript',
                         'Rust', 'Go', 'Java', 'HTTP', 'HTTPS', 'WebSocket', 'SSE', 'OAuth',
                         'JWT', 'GraphQL', 'REST', 'CLI', 'ORM', 'CI/CD', 'Git', 'GitHub'}
        entities.update(e for e in tech_keywords if e.lower() in text.lower())
        return list(entities)

    def get_realtime_context(self, query: str, top_k: int = 5) -> dict:
        """获取融合了短期、长期、图谱、画像、全局知识的实时上下文。
        返回带置信度的上下文字段，供 Agent 的 Perception 模块注入消息。

        Returns:
            dict with fields: short_term, long_term, graph_context, user_profile,
                              global_knowledge, confidence
        """
        result = {
            "short_term": [],
            "long_term": [],
            "graph_context": "",
            "user_profile": "",
            "global_knowledge": "",
            "confidence": 0.5,
        }

        # 短期记忆（ChromaDB 向量搜索）
        if self.collection:
            try:
                results = self.search_memory(query, top_k)
                if results:
                    result["short_term"] = results
                    result["confidence"] += 0.1
            except Exception:
                pass

        # 长期记忆（最近 N 条）
        try:
            recent = self.get_recent_nodes(min(top_k, 10))
            if recent:
                result["long_term"] = [recent]
                result["confidence"] += 0.05
        except Exception:
            pass

        # 图谱上下文
        try:
            graph_ctx = self.get_graph_context(query, depth=2)
            if graph_ctx:
                result["graph_context"] = graph_ctx
                result["confidence"] += 0.1
        except Exception:
            pass

        # 用户画像
        try:
            profile = self.get_user_profile()
            if profile:
                result["user_profile"] = profile
                result["confidence"] += 0.05
        except Exception:
            pass

        # 全局知识
        try:
            gk = self.get_global_knowledge()
            if gk:
                result["global_knowledge"] = gk
                result["confidence"] += 0.05
        except Exception:
            pass

        result["confidence"] = min(result["confidence"], 1.0)
        return result

    def adjust_memory_weight(self, memory_id: str, delta: float = 0.1):
        """根据反馈调整记忆权重（被引用并验证正确则增加，被纠正则降低）"""
        if memory_id in self.graph.nodes:
            node = self.graph.nodes[memory_id]
            old_weight = node.get("importance", 1.0)
            new_weight = max(0.1, min(5.0, old_weight + delta))
            node["importance"] = new_weight
            node["last_access"] = time.time()
            node["access_count"] = node.get("access_count", 0) + 1
            self._save_graph()
            logger.debug(f"记忆 [{memory_id}] 权重调整: {old_weight:.2f} → {new_weight:.2f}")

    def boost_memory_weight(self, memory_id: str, boost: float = 0.2):
        """提升记忆权重（当记忆在下游任务中被验证正确时）"""
        self.adjust_memory_weight(memory_id, abs(boost))

    def decrease_memory_weight(self, memory_id: str, penalty: float = -0.2):
        """降低记忆权重（当记忆被纠正时）"""
        self.adjust_memory_weight(memory_id, -abs(penalty))

    def get_recent_nodes(self, n=10):
        lines = []
        if self.long_term_path.exists():
            with open(self.long_term_path, "r", encoding="utf-8") as f: lines = f.readlines()
        recent = lines[-n:]
        result = []
        for line in recent:
            try:
                entry = json.loads(line); result.append(f"{entry['id']}: {entry['text'][:80]}")
            except Exception:
                pass
        return "\n".join(result)

    def get_graph_context(self, query: str, depth: int = 2) -> str:
        query_entities = self._extract_entities(query)
        seeds = [n for n in self.graph.nodes if set(query_entities) & set(self.graph.nodes[n].get("entities", []))]
        if not seeds:
            nodes = sorted(self.graph.nodes(data=True), key=lambda x: x[1].get("importance",1), reverse=True)
            texts = [data.get("text","") for _, data in nodes[:10]]
            return "\n".join(texts)
        sub_nodes = set(seeds)
        for _ in range(depth):
            neighbors = set()
            for n in sub_nodes: neighbors.update(self.graph.neighbors(n))
            sub_nodes.update(neighbors)
        node_list = [(n, self.graph.nodes[n]) for n in sub_nodes]
        node_list.sort(key=lambda x: x[1].get("importance",1)*x[1].get("access_count",0), reverse=True)
        texts = [data.get("text","") for _, data in node_list[:10]]
        for n in seeds:
            if n in self.graph.nodes:
                self.graph.nodes[n]["access_count"] = self.graph.nodes[n].get("access_count",0) + 1
                self.graph.nodes[n]["last_access"] = time.time()
        self._save_graph()
        return "\n".join(texts)

    def get_user_profile(self) -> str:
        if self.user_profile_path.exists(): return self.user_profile_path.read_text(encoding="utf-8").strip()
        return ""
    def update_user_profile(self, new_profile: str): self.user_profile_path.write_text(new_profile, encoding="utf-8")
    def get_global_knowledge(self) -> str:
        if self.global_knowledge_path.exists(): return self.global_knowledge_path.read_text(encoding="utf-8").strip()
        return ""
    def update_global_knowledge(self, content: str): self.global_knowledge_path.write_text(content, encoding="utf-8")
    def archive_low_weight_memories(self):
        if not self.long_term_path.exists(): return
        lines = self.long_term_path.read_text(encoding="utf-8").split("\n")
        active, archived = [], []
        now = time.time(); threshold = 0.3
        for line in lines:
            if not line.strip(): continue
            try:
                entry = json.loads(line)
                days = (now - entry.get("created_at", now)) / 86400
                current_weight = entry.get("importance", 1.0) * (0.9 ** days)
                if current_weight < threshold: archived.append(line)
                else: active.append(line)
            except Exception: active.append(line)
        if active: self.long_term_path.write_text("\n".join(active[:500]), encoding="utf-8")
        if archived:
            existing_archived = self.archive_path.read_text(encoding="utf-8").split("\n") if self.archive_path.exists() else []
            self.archive_path.write_text("\n".join(existing_archived[-1000:] + archived), encoding="utf-8")
    def _build_knowledge_graph(self):
        self.graph.clear()
        if not self.long_term_path.exists(): return
        lines = self.long_term_path.read_text(encoding="utf-8").split("\n")
        for line in lines:
            if not line.strip(): continue
            try:
                entry = json.loads(line); nid = entry.get("id", str(uuid.uuid4())[:8])
                self.graph.add_node(nid, text=entry["text"], importance=entry.get("importance",1.0), access_count=entry.get("access_count",0), last_access=entry.get("created_at",time.time()))
            except Exception:
                pass
        self._save_graph()
    def monthly_archive(self):
        now = datetime.now()
        # 用时间戳标记文件确保每月最多执行一次（而非依赖星期几判断）
        archive_flag = self.long_term_path.parent / ".archive_last_run"
        if archive_flag.exists():
            last_run = float(archive_flag.read_text().strip())
            if time.time() - last_run < 86400 * 28:  # 28天内已执行则跳过
                return
        archive_flag.write_text(str(time.time()))
        last_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
        archive_path = self.long_term_path.parent / f"archive_{last_month}.md"
        if archive_path.exists(): return
        lines = []
        if self.long_term_path.exists():
            with open(self.long_term_path, "r", encoding="utf-8") as f: lines = f.readlines()
        month_start = (now.replace(day=1) - timedelta(days=1)).replace(day=1).timestamp()
        month_end = now.replace(day=1).timestamp()
        month_entries = []
        for line in lines:
            try:
                entry = json.loads(line)
                if month_start <= entry.get("created_at", 0) < month_end: month_entries.append(entry["text"])
            except Exception:
                pass
        if not month_entries: return
        summary = "\n".join(month_entries[:50])
        prompt = f"请为以下记忆生成月度摘要，包含关键主题和重要结论。\n记忆内容：\n{summary}"
        try:
            if self.llm_manager: archive_path.write_text(self.llm_manager.chat([{"role":"user","content":prompt}]), encoding="utf-8")
        except Exception as e:
            logger.warning(f"月度归档失败: {e}")
    def _text_search(self, query: str, top_k: int = 5, mem_types: list = None) -> List[str]:
        results = []
        if not self.long_term_path.exists():
            return results
        query_lower = query.lower()
        with open(self.long_term_path, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                    if mem_types and entry.get("type") not in mem_types:
                        continue
                    text = entry.get("text", "")
                    score = sum(1 for word in query_lower.split() if word in text.lower())
                    if score > 0:
                        results.append((score, text))
                except Exception:
                    pass
        results.sort(key=lambda x: x[0], reverse=True)
        return [text for _, text in results[:top_k]]

    def _semantic_search(self, query: str, top_k: int = 5, mem_types: list = None) -> List[str]:
        try:
            if mem_types:
                res = self.collection.query(query_texts=[query], n_results=top_k, where={"type": {"$in": mem_types}})
            else:
                res = self.collection.query(query_texts=[query], n_results=top_k)
            return res["documents"][0] if res["documents"] else []
        except Exception:
            try:
                res = self.collection.query(query_texts=[query], n_results=top_k)
                return res["documents"][0] if res["documents"] else []
            except Exception:
                return []

    def _merge_results(self, semantic: List[str], text: List[str], top_k: int = 5) -> List[str]:
        seen = set()
        merged = []
        for item in semantic + text:
            key = item[:50]
            if key not in seen:
                seen.add(key)
                merged.append(item)
        return merged[:top_k]

    def save(self): pass

    def store_media(self, media_id: str, media_type: str, media_data: str, metadata: dict = None) -> bool:
        """存储媒体 base64 数据到磁盘"""
        ext_map = {"image": "jpg", "audio": "bin", "image_analysis": "jpg", "audio_analysis": "bin"}
        ext = ext_map.get(media_type, "bin")
        try:
            import base64
            data = base64.b64decode(media_data)
            (self.media_dir / f"{media_id}.{ext}").write_bytes(data)
            if metadata:
                (self.media_dir / f"{media_id}.meta.json").write_text(
                    __import__("json").dumps(metadata, ensure_ascii=False), encoding="utf-8"
                )
            return True
        except Exception:
            return False

    def get_media(self, media_id: str) -> Optional[str]:
        """从磁盘取回 base64 媒体数据"""
        import base64 as b64_mod
        for f in self.media_dir.glob(f"{media_id}.*"):
            if f.suffix in (".jpg", ".png", ".gif", ".webp", ".bmp", ".bin", ".wav", ".mp3", ".ogg", ".flac", ".m4a"):
                try:
                    return b64_mod.b64encode(f.read_bytes()).decode("utf-8")
                except Exception:
                    return None
        return None