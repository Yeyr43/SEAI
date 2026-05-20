"""
知识图谱引擎包 — Neo4j + NetworkX 双模式

此包替代了原来的 core/knowledge_graph.py 单文件，拆分为 5 个子模块：
- node_edge: KnowledgeNode, KnowledgeEdge
- neo4j_engine: Neo4jGraphEngine
- graph_rag: GraphRAGEngine
- temporal: TemporalKnowledgeGraph
- manager: KnowledgeGraphManager
"""
from .node_edge import KnowledgeNode, KnowledgeEdge
from .neo4j_engine import Neo4jGraphEngine
from .graph_rag import GraphRAGEngine
from .temporal import TemporalKnowledgeGraph
from .manager import KnowledgeGraphManager
