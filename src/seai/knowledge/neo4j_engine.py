"""Neo4j 图数据库引擎"""
import os
from typing import List, Dict
from loguru import logger
from .node_edge import KnowledgeNode, KnowledgeEdge

NEO4J_AVAILABLE = False
try:
    from neo4j import GraphDatabase, basic_auth
    NEO4J_AVAILABLE = True
except ImportError:
    logger.info("neo4j 驱动未安装，使用 NetworkX 本地模式")


class Neo4jGraphEngine:
    """Neo4j 图数据库引擎"""

    def __init__(self, uri: str = None, user: str = None, password: str = None, database: str = "neo4j"):
        self.uri = uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self.user = user or os.environ.get("NEO4J_USER", "neo4j")
        self.password = password or os.environ.get("NEO4J_PASSWORD", "neo4j")
        self.database = database
        self._driver = None
        self._connected = False

    def connect(self) -> bool:
        if not NEO4J_AVAILABLE:
            return False
        try:
            self._driver = GraphDatabase.driver(self.uri, auth=basic_auth(self.user, self.password))
            self._driver.verify_connectivity()
            self._connected = True
            self._init_schema()
            logger.info(f"Neo4j 连接成功: {self.uri}")
            return True
        except Exception as e:
            logger.warning(f"Neo4j 连接失败 ({self.uri}): {e}，降级为 NetworkX 模式")
            self._connected = False
            return False

    def _init_schema(self):
        with self._driver.session(database=self.database) as session:
            session.run("CREATE INDEX IF NOT EXISTS FOR (n:KnowledgeNode) ON (n.id)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (n:KnowledgeNode) ON (n.node_type)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (n:KnowledgeNode) ON (n.importance)")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._driver is not None

    def close(self):
        if self._driver:
            self._driver.close()
            self._connected = False

    def add_node(self, node: KnowledgeNode):
        with self._driver.session(database=self.database) as session:
            session.run(
                """MERGE (n:KnowledgeNode {id: $id})
                SET n.text = $text, n.node_type = $node_type, n.importance = $importance,
                    n.access_count = $access_count, n.last_access = $last_access,
                    n.created_at = $created_at, n.entities = $entities, n.version = $version""",
                id=node.id, text=node.text, node_type=node.node_type,
                importance=node.importance, access_count=node.access_count,
                last_access=node.last_access, created_at=node.created_at,
                entities=node.entities, version=node.version
            )

    def add_edge(self, edge: KnowledgeEdge):
        with self._driver.session(database=self.database) as session:
            session.run(
                """MATCH (a:KnowledgeNode {id: $source})
                MATCH (b:KnowledgeNode {id: $target})
                MERGE (a)-[r:RELATES {relation: $relation}]->(b)
                SET r.weight = $weight, r.created_at = $created_at""",
                source=edge.source, target=edge.target,
                relation=edge.relation, weight=edge.weight, created_at=edge.created_at
            )

    def search_subgraph(self, query_entities: List[str], depth: int = 2, limit: int = 20) -> List[Dict]:
        with self._driver.session(database=self.database) as session:
            safe_entities = [e.replace("'", "\\'").replace('"', '\\"')[:200] for e in query_entities[:5]]
            entity_conditions = " OR ".join([f"n.text CONTAINS $entity_{i}" for i in range(len(safe_entities))])
            if not entity_conditions:
                entity_conditions = "1=1"
            params = {f"entity_{i}": e for i, e in enumerate(safe_entities)}
            params["limit"] = limit
            result = session.run(
                f"""MATCH (n:KnowledgeNode) WHERE {entity_conditions}
                OPTIONAL MATCH (n)-[r:RELATES*1..{depth}]-(related:KnowledgeNode)
                WITH n, related, r
                RETURN n.id AS id, n.text AS text, n.node_type AS node_type,
                       n.importance AS importance, n.access_count AS access_count,
                       collect(DISTINCT related.id) AS related_ids
                ORDER BY n.importance * (n.access_count + 1) DESC LIMIT $limit""",
                **params
            )
            return [record.data() for record in result]

    def get_node_neighbors(self, node_id: str, depth: int = 1) -> List[Dict]:
        with self._driver.session(database=self.database) as session:
            result = session.run(
                """MATCH (n:KnowledgeNode {id: $id})-[r:RELATES*1..$depth]-(neighbor:KnowledgeNode)
                RETURN DISTINCT neighbor.id AS id, neighbor.text AS text,
                       neighbor.node_type AS node_type, neighbor.importance AS importance
                ORDER BY neighbor.importance DESC LIMIT 30""",
                id=node_id, depth=depth
            )
            return [record.data() for record in result]

    def get_temporal_evolution(self, node_id: str) -> List[Dict]:
        with self._driver.session(database=self.database) as session:
            result = session.run(
                """MATCH (n:KnowledgeNode {id: $id})
                OPTIONAL MATCH (n)-[:EVOLVED_FROM*]->(prev:KnowledgeNode)
                OPTIONAL MATCH (next:KnowledgeNode)-[:EVOLVED_FROM*]->(n)
                RETURN n.id AS id, n.text AS text, n.version AS version,
                       n.created_at AS created_at,
                       collect(DISTINCT prev.id) AS ancestors,
                       collect(DISTINCT next.id) AS descendants""",
                id=node_id
            )
            return [r.data() for r in result]

    def get_stats(self) -> Dict:
        with self._driver.session(database=self.database) as session:
            result = session.run(
                """MATCH (n:KnowledgeNode)
                OPTIONAL MATCH (n)-[r:RELATES]-()
                RETURN count(DISTINCT n) AS node_count,
                       count(DISTINCT r) AS edge_count,
                       avg(n.importance) AS avg_importance"""
            )
            record = result.single()
            if record:
                return {"node_count": record["node_count"], "edge_count": record["edge_count"],
                        "avg_importance": round(record["avg_importance"] or 0, 3)}
            return {"node_count": 0, "edge_count": 0, "avg_importance": 0}

    def delete_node(self, node_id: str):
        with self._driver.session(database=self.database) as session:
            session.run("MATCH (n:KnowledgeNode {id: $id}) DETACH DELETE n", id=node_id)

    def clear_all(self):
        with self._driver.session(database=self.database) as session:
            session.run("MATCH (n) DETACH DELETE n")
