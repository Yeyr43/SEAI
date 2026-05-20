"""GraphRAG — 图谱增强检索生成引擎"""
import re
from typing import List, Dict
from ..lazy_import import LazyImport

tiktoken_lazy = LazyImport("tiktoken", "pip install tiktoken")


class GraphRAGEngine:
    """GraphRAG：图谱增强检索生成引擎"""

    def __init__(self, graph_engine):
        self.graph = graph_engine

    def retrieve(self, query: str, depth: int = 2, top_k: int = 10,
                 preferred_types: List[str] = None) -> str:
        entities = self._extract_entities(query)
        if self.graph.is_connected:
            nodes = self.graph.search_subgraph(entities, depth, top_k)
            if preferred_types:
                nodes = [n for n in nodes if n.get("node_type") in preferred_types]
            texts = [n.get("text", "") for n in nodes[:top_k]]
            return "\n".join(texts) if texts else ""
        return ""

    def retrieve_with_relations(self, query: str, depth: int = 2, top_k: int = 10) -> List[Dict]:
        entities = self._extract_entities(query)
        if self.graph.is_connected:
            nodes = self.graph.search_subgraph(entities, depth, top_k)
            enriched = []
            for node in nodes[:top_k]:
                neighbors = self.graph.get_node_neighbors(node["id"], depth=1)
                node["neighbors"] = [n["text"][:100] for n in neighbors[:5]]
                enriched.append(node)
            return enriched
        return []

    def build_rag_context(self, query: str, depth: int = 2, max_tokens: int = 2000) -> str:
        context = self.retrieve(query, depth, top_k=15)
        if not context:
            return ""
        lines = context.split("\n")
        result, token_est = [], 0
        if tiktoken_lazy.available:
            enc = tiktoken_lazy.get().get_encoding("cl100k_base")
            for line in lines:
                est = len(enc.encode(line))
                if token_est + est > max_tokens:
                    break
                result.append(line)
                token_est += est
        else:
            for line in lines:
                est = len(line) // 2
                if token_est + est > max_tokens:
                    break
                result.append(line)
                token_est += est
        return "\n".join(result)

    @staticmethod
    def _extract_entities(text: str) -> List[str]:
        patterns = [
            r'[A-Z][a-z]+',
            r'[0-9]+',
            r'Python|FastAPI|Windows|Linux|API|json|sqlite|Neo4j|Docker|Redis|PostgreSQL',
            r'[一-龥]{2,8}'
        ]
        entities = []
        for pattern in patterns:
            entities.extend(re.findall(pattern, text))
        return list(set(entities))[:20]
