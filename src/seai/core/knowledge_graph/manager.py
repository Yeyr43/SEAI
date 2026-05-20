"""知识图谱管理器 — 统一 Neo4j + NetworkX 双模式"""
import json
import time
import uuid
from pathlib import Path
from typing import List, Dict
import networkx as nx
from loguru import logger
from .node_edge import KnowledgeNode, KnowledgeEdge
from .neo4j_engine import Neo4jGraphEngine
from .graph_rag import GraphRAGEngine
from .temporal import TemporalKnowledgeGraph


class KnowledgeGraphManager:
    """知识图谱管理器：统一 Neo4j + NetworkX 双模式"""

    def __init__(self, persist_dir: Path):
        self.persist_dir = persist_dir
        self.persist_dir.mkdir(parents=True, exist_ok=True)

        self.neo4j = Neo4jGraphEngine()
        self._nx_graph = nx.Graph()
        self._nx_path = persist_dir / "knowledge_graph_nx.json"

        self.graph_rag = GraphRAGEngine(self.neo4j)
        self.temporal = TemporalKnowledgeGraph(persist_dir)

        self._load_nx()

    def initialize(self) -> bool:
        neo4j_ok = self.neo4j.connect()
        if neo4j_ok:
            logger.info("知识图谱: Neo4j 模式")
        else:
            logger.info("知识图谱: NetworkX 本地模式")
        return neo4j_ok

    @property
    def mode(self) -> str:
        return "neo4j" if self.neo4j.is_connected else "networkx"

    def _load_nx(self):
        if self._nx_path.exists():
            try:
                data = json.loads(self._nx_path.read_text(encoding="utf-8"))
                self._nx_graph = nx.node_link_graph(data)
            except Exception as exc:
                logger.warning("Failed to load graph from {}: {}", self._nx_path, exc)
                self._nx_graph = nx.Graph()
        else:
            _old_pkl = self._nx_path.with_suffix(".pkl")
            if _old_pkl.exists():
                try:
                    import pickle
                    self._nx_graph = pickle.load(open(_old_pkl, "rb"))
                    self._save_nx()
                    _old_pkl.unlink()
                    logger.info("Migrated knowledge graph from pickle to JSON")
                except Exception as exc:
                    logger.warning("Pickle migration failed: {}", exc)
                    self._nx_graph = nx.Graph()

    def _save_nx(self):
        data = nx.node_link_data(self._nx_graph)
        self._nx_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def add_knowledge(self, text: str, node_type: str = "concept", importance: float = 1.0,
                      relations: Dict[str, str] = None) -> str:
        node_id = str(uuid.uuid4())[:8]
        entities = GraphRAGEngine._extract_entities(text)

        node = KnowledgeNode(id=node_id, text=text, node_type=node_type,
                             importance=importance, entities=entities)

        if self.neo4j.is_connected:
            self.neo4j.add_node(node)
            if relations:
                for target_id, rel_type in relations.items():
                    edge = KnowledgeEdge(source=node_id, target=target_id, relation=rel_type)
                    self.neo4j.add_edge(edge)

        self._nx_graph.add_node(node_id, text=text, type=node_type, importance=importance,
                                 entities=entities, access_count=0, last_access=time.time())
        if relations:
            for target_id, rel_type in relations.items():
                if target_id in self._nx_graph.nodes:
                    weight = 3 if rel_type == "similar" else (2 if rel_type == "cause" else 1)
                    self._nx_graph.add_edge(node_id, target_id, relation=rel_type, weight=weight)
        for existing in self._nx_graph.nodes:
            if existing == node_id:
                continue
            common = set(entities) & set(self._nx_graph.nodes[existing].get("entities", []))
            if common:
                self._nx_graph.add_edge(node_id, existing, weight=len(common))
        self._save_nx()

        self.temporal.record_evolution(node_id, "create", new_text=text, reason=f"新增{node_type}类型知识")
        return node_id

    def search(self, query: str, depth: int = 2, top_k: int = 10,
               preferred_types: List[str] = None) -> str:
        if self.neo4j.is_connected:
            result = self.graph_rag.retrieve(query, depth, top_k, preferred_types)
            if result:
                return result

        entities = GraphRAGEngine._extract_entities(query)
        seeds = [n for n in self._nx_graph.nodes
                 if set(entities) & set(self._nx_graph.nodes[n].get("entities", []))]
        if not seeds:
            nodes = sorted(self._nx_graph.nodes(data=True),
                           key=lambda x: x[1].get("importance", 1), reverse=True)
            texts = [data.get("text", "") for _, data in nodes[:top_k]]
            return "\n".join(texts)

        sub_nodes = set(seeds)
        for _ in range(depth):
            neighbors = set()
            for n in sub_nodes:
                neighbors.update(self._nx_graph.neighbors(n))
            sub_nodes.update(neighbors)

        node_list = [(n, self._nx_graph.nodes[n]) for n in sub_nodes]
        if preferred_types:
            node_list = [(n, d) for n, d in node_list if d.get("type") in preferred_types]
        node_list.sort(key=lambda x: x[1].get("importance", 1) * x[1].get("access_count", 0),
                       reverse=True)
        texts = [data.get("text", "") for _, data in node_list[:top_k]]

        for n in seeds:
            if n in self._nx_graph.nodes:
                self._nx_graph.nodes[n]["access_count"] = self._nx_graph.nodes[n].get("access_count", 0) + 1
                self._nx_graph.nodes[n]["last_access"] = time.time()
        self._save_nx()
        return "\n".join(texts)

    def update_knowledge(self, node_id: str, new_text: str, reason: str = ""):
        old_text = ""
        if node_id in self._nx_graph.nodes:
            old_text = self._nx_graph.nodes[node_id].get("text", "")
            self._nx_graph.nodes[node_id]["text"] = new_text
            self._save_nx()
        if self.neo4j.is_connected:
            node = KnowledgeNode(id=node_id, text=new_text, version=2)
            self.neo4j.add_node(node)
        self.temporal.record_evolution(node_id, "update", old_text=old_text, new_text=new_text, reason=reason)

    def delete_knowledge(self, node_id: str, reason: str = ""):
        old_text = ""
        if node_id in self._nx_graph.nodes:
            old_text = self._nx_graph.nodes[node_id].get("text", "")
            self._nx_graph.remove_node(node_id)
            self._save_nx()
        if self.neo4j.is_connected:
            self.neo4j.delete_node(node_id)
        self.temporal.record_evolution(node_id, "delete", old_text=old_text, reason=reason)

    def get_stats(self) -> Dict:
        stats = {"mode": self.mode, "nx_nodes": self._nx_graph.number_of_nodes(),
                 "nx_edges": self._nx_graph.number_of_edges()}
        if self.neo4j.is_connected:
            neo4j_stats = self.neo4j.get_stats()
            stats.update({f"neo4j_{k}": v for k, v in neo4j_stats.items()})
        return stats

    def get_graph_data(self) -> Dict:
        nodes, edges = [], []
        for nid, data in self._nx_graph.nodes(data=True):
            nodes.append({"id": nid, "text": data.get("text", "")[:100],
                          "type": data.get("type", "concept"), "importance": data.get("importance", 1.0)})
        for u, v, data in self._nx_graph.edges(data=True):
            edges.append({"source": u, "target": v, "relation": data.get("relation", ""),
                          "weight": data.get("weight", 1)})
        return {"nodes": nodes, "edges": edges}

    def create_snapshot(self, label: str = ""):
        graph_data = self.get_graph_data()
        return self.temporal.create_snapshot(label, graph_data)

    def close(self):
        if self.neo4j:
            self.neo4j.close()
