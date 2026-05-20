//! HTTP 客户端 — reqwest + 指数退避 + multi-endpoint fallback
//!
//! 对应 Python: core/llm_manager.py (_retry_with_fallback)

use pyo3::prelude::*;
use reqwest::blocking::Client;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Duration;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<LlmClient>()?;
    Ok(())
}

#[pyclass]
pub struct LlmClient {
    client: Mutex<Option<Client>>,
    endpoints: Mutex<Vec<(String, String, f32)>>, // (url, label, priority)
    default_timeout: u64,
    max_retries: u32,
}

#[pymethods]
impl LlmClient {
    #[new]
    fn new(timeout_secs: Option<u64>, max_retries: Option<u32>) -> Self {
        LlmClient {
            client: Mutex::new(None),
            endpoints: Mutex::new(Vec::new()),
            default_timeout: timeout_secs.unwrap_or(120),
            max_retries: max_retries.unwrap_or(3),
        }
    }

    /// 初始化 HTTP 客户端
    fn init(&self) -> bool {
        let c = Client::builder()
            .timeout(Duration::from_secs(self.default_timeout))
            .pool_max_idle_per_host(10)
            .build();
        match c {
            Ok(client) => {
                *self.client.lock().unwrap() = Some(client);
                true
            }
            Err(_) => false,
        }
    }

    /// 添加 API 端点（按优先级排序）
    fn add_endpoint(&self, url: &str, label: &str, priority: f32) {
        self.endpoints
            .lock()
            .unwrap()
            .push((url.to_string(), label.to_string(), priority));
    }

    /// 清空端点
    fn clear_endpoints(&self) {
        self.endpoints.lock().unwrap().clear();
    }

    /// 同步聊天请求（带重试 + 端点 fallback）
    fn chat(&self, api_key: &str, model: &str, messages_json: &str) -> PyResult<String> {
        let client = self.client.lock().unwrap();
        let client = client.as_ref().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("Client not initialized, call init() first")
        })?;

        let mut endpoints = self.endpoints.lock().unwrap().clone();
        endpoints.sort_by(|a, b| b.2.partial_cmp(&a.2).unwrap_or(std::cmp::Ordering::Equal));

        let body: Value = serde_json::json!({
            "model": model,
            "messages": serde_json::from_str::<Value>(messages_json).unwrap_or(serde_json::json!([])),
            "max_tokens": 4096,
        });

        let mut last_error = String::new();

        for (url, _label, _priority) in &endpoints {
            for attempt in 0..self.max_retries {
                if attempt > 0 {
                    let backoff = 2u64.pow(attempt) * 100;
                    let jitter = (backoff as f64 * 0.3) as u64;
                    let wait = backoff + jitter;
                    std::thread::sleep(Duration::from_millis(wait.min(10000)));
                }

                match client
                    .post(url)
                    .header("Authorization", format!("Bearer {}", api_key))
                    .header("Content-Type", "application/json")
                    .json(&body)
                    .send()
                {
                    Ok(resp) => match resp.text() {
                        Ok(text) => {
                            // Parse response to extract content
                            if let Ok(v) = serde_json::from_str::<Value>(&text) {
                                if let Some(choices) = v["choices"].as_array() {
                                    if let Some(choice) = choices.first() {
                                        if let Some(content) = choice["message"]["content"].as_str() {
                                            return Ok(content.to_string());
                                        }
                                    }
                                }
                                if let Some(error) = v["error"].as_object() {
                                    last_error = error
                                        .get("message")
                                        .and_then(|m| m.as_str())
                                        .unwrap_or(&text)
                                        .to_string();
                                    continue;
                                }
                            }
                            return Ok(text.to_string());
                        }
                        Err(e) => {
                            last_error = format!("Response read error: {}", e);
                        }
                    },
                    Err(e) => {
                        last_error = format!("Request error: {}", e);
                    }
                }
            }
        }

        Err(pyo3::exceptions::PyRuntimeError::new_err(format!(
            "All endpoints failed after retries. Last error: {}",
            last_error
        )))
    }

    /// 健康检查 — 测试到端点的连通性
    fn health_check(&self, url: &str) -> PyResult<String> {
        let client = self.client.lock().unwrap();
        let client = client.as_ref().ok_or_else(|| {
            pyo3::exceptions::PyRuntimeError::new_err("Client not initialized")
        })?;

        let start = std::time::Instant::now();
        match client.get(url).timeout(Duration::from_secs(10)).send() {
            Ok(resp) => {
                let status = resp.status().as_u16();
                let latency = start.elapsed().as_millis();
                Ok(format!("{{\"status\":{},\"latency_ms\":{}}}", status, latency))
            }
            Err(e) => Ok(format!("{{\"error\":\"{}\"}}", e)),
        }
    }

    fn health(&self) -> &'static str {
        "http_client: operational (reqwest + exponential backoff)"
    }
}
