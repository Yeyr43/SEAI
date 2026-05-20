//! 知识图谱 — petgraph 图引擎 + 序列化
//!
//! 对应 Python: core/knowledge_graph/manager.py

use pyo3::prelude::*;
use petgraph::graph::{Graph, NodeIndex};
use petgraph::visit::IntoNodeReferences;
use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};
use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustKnowledgeGraph>()?;
    Ok(())
}

#[derive(Clone, Serialize, Deserialize)]
struct GraphData {
    nodes: Vec<NodeData>,
    edges: Vec<EdgeData>,
}

#[derive(Clone, Serialize, Deserialize)]
struct NodeData {
    id: String,
    text: String,
    node_type: String,
    importance: f32,
    access_count: u32,
}

#[derive(Clone, Serialize, Deserialize)]
struct EdgeData {
    source: String,
    target: String,
    weight: f32,
}

#[pyclass]
pub struct RustKnowledgeGraph {
    graph: Mutex<Graph<String, f32>>,
    node_ids: Mutex<HashMap<String, NodeIndex>>,
    node_texts: Mutex<HashMap<NodeIndex, String>>,
    node_types: Mutex<HashMap<NodeIndex, String>>,
    node_importance: Mutex<HashMap<NodeIndex, f32>>,
    node_access: Mutex<HashMap<NodeIndex, u32>>,
    persist_path: Mutex<Option<PathBuf>>,
}

#[pymethods]
impl RustKnowledgeGraph {
    #[new]
    fn new() -> Self {
        RustKnowledgeGraph {
            graph: Mutex::new(Graph::new()),
            node_ids: Mutex::new(HashMap::new()),
            node_texts: Mutex::new(HashMap::new()),
            node_types: Mutex::new(HashMap::new()),
            node_importance: Mutex::new(HashMap::new()),
            node_access: Mutex::new(HashMap::new()),
            persist_path: Mutex::new(None),
        }
    }

    fn set_persist_path(&self, path: &str) -> PyResult<bool> {
        let pb = PathBuf::from(path);
        *self.persist_path.lock().unwrap() = Some(pb.clone());
        if pb.exists() {
            self.load_from_disk(&pb);
        }
        Ok(true)
    }

    fn add_node(&self, id: &str, text: &str, node_type: &str, importance: f32) -> bool {
        let mut graph = self.graph.lock().unwrap();
        let mut node_ids = self.node_ids.lock().unwrap();
        if node_ids.contains_key(id) {
            return false;
        }
        let idx = graph.add_node(id.to_string());
        node_ids.insert(id.to_string(), idx);
        self.node_texts.lock().unwrap().insert(idx, text.to_string());
        self.node_types.lock().unwrap().insert(idx, node_type.to_string());
        self.node_importance.lock().unwrap().insert(idx, importance);
        self.node_access.lock().unwrap().insert(idx, 0);
        true
    }

    fn add_edge(&self, source: &str, target: &str, relation: &str) -> bool {
        let node_ids = self.node_ids.lock().unwrap();
        let source_idx = node_ids.get(source);
        let target_idx = node_ids.get(target);
        let weight = match relation {
            "similar" => 3.0,
            "cause" => 2.0,
            _ => 1.0,
        };
        match (source_idx, target_idx) {
            (Some(&s), Some(&t)) => {
                self.graph.lock().unwrap().add_edge(s, t, weight);
                true
            }
            _ => false,
        }
    }

    fn search(&self, query: &str, depth: usize, top_k: usize) -> PyResult<Vec<String>> {
        let graph = self.graph.lock().unwrap();
        let node_texts = self.node_texts.lock().unwrap();
        let node_imp = self.node_importance.lock().unwrap();
        let mut node_access = self.node_access.lock().unwrap();

        let query_lower = query.to_lowercase();
        let mut seeds: Vec<NodeIndex> = graph
            .node_references()
            .filter(|(_, name)| name.to_lowercase().contains(&query_lower))
            .map(|(idx, _)| idx)
            .collect();

        if seeds.is_empty() {
            let mut nodes: Vec<(NodeIndex, f32)> = graph
                .node_references()
                .map(|(idx, _)| {
                    let imp = node_imp.get(&idx).copied().unwrap_or(1.0);
                    (idx, imp)
                })
                .collect();
            nodes.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
            seeds = nodes.into_iter().take(5).map(|(idx, _)| idx).collect();
        }

        let mut visited: HashSet<NodeIndex> = seeds.iter().copied().collect();
        let mut frontier: Vec<NodeIndex> = seeds.clone();
        for _ in 0..depth {
            let mut next = Vec::new();
            for &n in &frontier {
                for neighbor in graph.neighbors(n) {
                    if visited.insert(neighbor) {
                        next.push(neighbor);
                    }
                }
            }
            frontier = next;
        }

        let mut results: Vec<(String, f32)> = visited
            .iter()
            .map(|&idx| {
                let text = node_texts.get(&idx).cloned().unwrap_or_default();
                let imp = node_imp.get(&idx).copied().unwrap_or(1.0);
                let acc = node_access.get(&idx).copied().unwrap_or(0);
                let score = imp * (1.0 + acc as f32 * 0.1);
                (text, score)
            })
            .collect();
        results.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        results.truncate(top_k);

        for idx in seeds {
            if let Some(count) = node_access.get_mut(&idx) {
                *count += 1;
            }
        }

        Ok(results.into_iter().map(|(t, _)| t).collect())
    }

    fn remove_node(&self, id: &str) -> bool {
        let mut graph = self.graph.lock().unwrap();
        let mut node_ids = self.node_ids.lock().unwrap();
        if let Some(&idx) = node_ids.get(id) {
            graph.remove_node(idx);
            node_ids.remove(id);
            self.node_texts.lock().unwrap().remove(&idx);
            self.node_types.lock().unwrap().remove(&idx);
            self.node_importance.lock().unwrap().remove(&idx);
            self.node_access.lock().unwrap().remove(&idx);
            true
        } else {
            false
        }
    }

    fn get_stats(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let graph = self.graph.lock().unwrap();
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("nodes", graph.node_count())?;
            dict.set_item("edges", graph.edge_count())?;
            Ok(dict.into())
        })
    }

    fn save_to_disk(&self) -> PyResult<bool> {
        if let Some(ref path) = *self.persist_path.lock().unwrap() {
            let graph = self.graph.lock().unwrap();
            let node_ids = self.node_ids.lock().unwrap();
            let node_texts = self.node_texts.lock().unwrap();
            let node_types = self.node_types.lock().unwrap();
            let node_imp = self.node_importance.lock().unwrap();
            let node_acc = self.node_access.lock().unwrap();

            let nodes: Vec<NodeData> = node_ids
                .iter()
                .map(|(id, idx)| NodeData {
                    id: id.clone(),
                    text: node_texts.get(idx).cloned().unwrap_or_default(),
                    node_type: node_types.get(idx).cloned().unwrap_or_default(),
                    importance: node_imp.get(idx).copied().unwrap_or(1.0),
                    access_count: node_acc.get(idx).copied().unwrap_or(0),
                })
                .collect();

            let edges: Vec<EdgeData> = graph
                .edge_indices()
                .map(|e| {
                    let (s, t) = graph.edge_endpoints(e).unwrap();
                    EdgeData {
                        source: graph[s].clone(),
                        target: graph[t].clone(),
                        weight: *graph.edge_weight(e).unwrap_or(&1.0),
                    }
                })
                .collect();

            let data = GraphData { nodes, edges };
            if let Ok(json) = serde_json::to_string_pretty(&data) {
                let _ = fs::write(path, json);
                return Ok(true);
            }
        }
        Ok(false)
    }

    fn health(&self) -> &'static str {
        "knowledge_graph: operational (petgraph)"
    }
}

impl RustKnowledgeGraph {
    fn load_from_disk(&self, path: &PathBuf) {
        if let Ok(json) = fs::read_to_string(path) {
            if let Ok(data) = serde_json::from_str::<GraphData>(&json) {
                for node in data.nodes {
                    self.add_node(&node.id, &node.text, &node.node_type, node.importance);
                }
                for edge in data.edges {
                    self.add_edge(&edge.source, &edge.target, "");
                }
            }
        }
    }
}
