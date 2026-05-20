//! 记忆引擎 — 向量余弦相似度搜索 + JSONL 持久化
//!
//! 对应 Python: core/memory_engine.py

use pyo3::prelude::*;
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::sync::Mutex;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustMemoryEngine>()?;
    Ok(())
}

fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() || a.is_empty() {
        return 0.0;
    }
    let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let norm_a: f32 = (a.iter().map(|x| x * x).sum::<f32>()).sqrt();
    let norm_b: f32 = (b.iter().map(|x| x * x).sum::<f32>()).sqrt();
    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }
    dot / (norm_a * norm_b)
}

#[derive(Serialize, Deserialize, Clone)]
struct MemoryEntry {
    id: String,
    content: String,
    embedding: Vec<f32>,
    metadata: serde_json::Value,
    timestamp: f64,
    access_count: u32,
}

#[pyclass]
pub struct RustMemoryEngine {
    entries: Mutex<Vec<MemoryEntry>>,
    storage_path: Mutex<Option<PathBuf>>,
    max_entries: usize,
}

#[pymethods]
impl RustMemoryEngine {
    #[new]
    fn new(max_entries: Option<usize>) -> Self {
        RustMemoryEngine {
            entries: Mutex::new(Vec::new()),
            storage_path: Mutex::new(None),
            max_entries: max_entries.unwrap_or(10000),
        }
    }

    fn set_storage_path(&self, path: &str) -> PyResult<bool> {
        let pb = PathBuf::from(path);
        *self.storage_path.lock().unwrap() = Some(pb.clone());
        if pb.exists() {
            self.load_from_disk(&pb);
        }
        Ok(true)
    }

    fn add_memory(&self, content: &str, embedding: Vec<f32>, metadata: &str) -> PyResult<String> {
        let id = uuid_str();
        let meta: serde_json::Value =
            serde_json::from_str(metadata).unwrap_or(serde_json::json!({}));
        let entry = MemoryEntry {
            id: id.clone(),
            content: content.to_string(),
            embedding,
            metadata: meta,
            timestamp: now_secs(),
            access_count: 0,
        };

        let mut entries = self.entries.lock().unwrap();
        entries.push(entry.clone());
        while entries.len() > self.max_entries {
            entries.remove(0);
        }

        if let Some(ref path) = *self.storage_path.lock().unwrap() {
            if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
                if let Ok(line) = serde_json::to_string(&entry) {
                    let _ = writeln!(f, "{}", line);
                }
            }
        }
        Ok(id)
    }

    fn search_memory(&self, query_embedding: Vec<f32>, top_k: usize) -> PyResult<Vec<(String, f32)>> {
        let mut entries = self.entries.lock().unwrap();
        let mut scored: Vec<(usize, f32)> = entries
            .iter()
            .enumerate()
            .map(|(i, e)| (i, cosine_similarity(&query_embedding, &e.embedding)))
            .collect();
        scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

        let results: Vec<(String, f32)> = scored
            .into_iter()
            .take(top_k)
            .map(|(i, score)| {
                entries[i].access_count += 1;
                (entries[i].content.clone(), score)
            })
            .collect();
        Ok(results)
    }

    fn search_text(&self, query: &str, top_k: usize) -> PyResult<Vec<(String, f32)>> {
        let query_lower = query.to_lowercase();
        let entries = self.entries.lock().unwrap();
        let mut results: Vec<(String, f32)> = Vec::new();
        for entry in entries.iter() {
            let content_lower = entry.content.to_lowercase();
            let score = if content_lower.contains(&query_lower) {
                0.9
            } else {
                let words: Vec<&str> = query_lower.split_whitespace().collect();
                let matches = words.iter().filter(|w| content_lower.contains(*w)).count();
                if words.is_empty() { 0.0 } else { matches as f32 / words.len() as f32 * 0.7 }
            };
            if score > 0.1 {
                results.push((entry.content.clone(), score));
            }
        }
        results.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
        results.truncate(top_k);
        Ok(results)
    }

    fn remove_memory(&self, id: &str) -> bool {
        let mut entries = self.entries.lock().unwrap();
        let before = entries.len();
        entries.retain(|e| e.id != id);
        entries.len() < before
    }

    fn clear(&self) {
        self.entries.lock().unwrap().clear();
    }

    fn get_stats(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let entries = self.entries.lock().unwrap();
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("total_entries", entries.len())?;
            dict.set_item("max_entries", self.max_entries)?;
            let dims: usize = entries.iter().map(|e| e.embedding.len()).sum();
            let avg = if entries.is_empty() { 0 } else { dims / entries.len() };
            dict.set_item("avg_embedding_dim", avg)?;
            Ok(dict.into())
        })
    }

    fn health(&self) -> &'static str {
        "memory_engine: operational (cosine similarity)"
    }
}

impl RustMemoryEngine {
    fn load_from_disk(&self, path: &PathBuf) {
        if let Ok(f) = File::open(path) {
            let reader = BufReader::new(f);
            let mut entries = self.entries.lock().unwrap();
            for line in reader.lines() {
                if let Ok(line) = line {
                    if let Ok(entry) = serde_json::from_str::<MemoryEntry>(&line) {
                        entries.push(entry);
                    }
                }
                if entries.len() >= self.max_entries { break; }
            }
        }
    }
}

fn uuid_str() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let t = SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default();
    format!("{:016x}", t.as_nanos())
}

fn now_secs() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    SystemTime::now().duration_since(UNIX_EPOCH).unwrap_or_default().as_secs_f64()
}
