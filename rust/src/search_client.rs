//! 多后端 Web 搜索客户端
//!
//! 对应 Python: core/infra/net.py
//!
//! 支持: DuckDuckGo (免费), Brave Search API, Serper.dev
//! 熔断器集成 + LRU 缓存 + 速率限制

use pyo3::prelude::*;
use reqwest::blocking::Client;
use serde_json::Value;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, AtomicU32, Ordering};
use std::sync::Mutex;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<SearchClient>()?;
    Ok(())
}

/// LRU 缓存条目
#[derive(Clone)]
struct CacheEntry {
    result: String,
    timestamp: u64,
}

/// 简易 LRU 缓存 (max 100 entries)
struct LruCache {
    entries: HashMap<String, CacheEntry>,
    order: Vec<String>,
    max_size: usize,
    ttl_secs: u64,
}

impl LruCache {
    fn new(max_size: usize, ttl_secs: u64) -> Self {
        LruCache { entries: HashMap::new(), order: Vec::new(), max_size, ttl_secs }
    }

    fn get(&mut self, key: &str) -> Option<String> {
        if let Some(entry) = self.entries.get(key) {
            let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
            if now - entry.timestamp < self.ttl_secs {
                // Move to end (most recently used)
                self.order.retain(|k| k != key);
                self.order.push(key.to_string());
                return Some(entry.result.clone());
            }
            // Expired
            self.entries.remove(key);
            self.order.retain(|k| k != key);
        }
        None
    }

    fn put(&mut self, key: String, value: String) {
        if self.entries.len() >= self.max_size {
            if let Some(oldest) = self.order.first().cloned() {
                self.entries.remove(&oldest);
                self.order.remove(0);
            }
        }
        self.order.retain(|k| k != &key);
        self.order.push(key.clone());
        self.entries.insert(key, CacheEntry {
            result: value,
            timestamp: SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs(),
        });
    }

    fn clear_expired(&mut self) {
        let now = SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_secs();
        self.entries.retain(|_, e| now - e.timestamp < self.ttl_secs);
        self.order.retain(|k| self.entries.contains_key(k));
    }
}

#[pyclass]
pub struct SearchClient {
    client: Mutex<Option<Client>>,
    cache: Mutex<LruCache>,
    ddg_count: AtomicU64,
    brave_count: AtomicU64,
    serper_count: AtomicU64,
    rate_window_start: Mutex<Instant>,
    rate_count: AtomicU32,
    max_requests_per_minute: u32,
    enabled: AtomicU32, // 0=disabled, 1=enabled (using u32 as AtomicBool)
}

#[pymethods]
impl SearchClient {
    #[new]
    fn new() -> Self {
        SearchClient {
            client: Mutex::new(None),
            cache: Mutex::new(LruCache::new(100, 300)),
            ddg_count: AtomicU64::new(0),
            brave_count: AtomicU64::new(0),
            serper_count: AtomicU64::new(0),
            rate_window_start: Mutex::new(Instant::now()),
            rate_count: AtomicU32::new(0),
            max_requests_per_minute: 10,
            enabled: AtomicU32::new(1),
        }
    }

    /// 初始化 HTTP 客户端
    fn init(&self) -> bool {
        let c = Client::builder()
            .timeout(Duration::from_secs(15))
            .build();
        match c {
            Ok(client) => {
                *self.client.lock().unwrap() = Some(client);
                true
            }
            Err(_) => false,
        }
    }

    /// 启用/禁用搜索
    fn set_enabled(&self, val: bool) {
        self.enabled.store(if val { 1 } else { 0 }, Ordering::Relaxed);
    }

    fn is_enabled(&self) -> bool {
        self.enabled.load(Ordering::Relaxed) == 1
    }

    /// 速率检查
    fn check_rate_limit(&self) -> bool {
        let mut window_start = self.rate_window_start.lock().unwrap();
        let elapsed = window_start.elapsed().as_secs();
        if elapsed > 60 {
            *window_start = Instant::now();
            self.rate_count.store(0, Ordering::Relaxed);
        }
        let count = self.rate_count.fetch_add(1, Ordering::Relaxed);
        count < self.max_requests_per_minute
    }

    /// 清除过期缓存
    fn clean_cache(&self) {
        self.cache.lock().unwrap().clear_expired();
    }

    /// 主搜索入口 — 多后端 fallback
    fn search(&self, query: &str, max_results: Option<usize>, backend: Option<&str>) -> String {
        if !self.is_enabled() {
            return "联网搜索功能未启用。".to_string();
        }

        if !self.check_rate_limit() {
            return "搜索频率过高，请稍后再试（每分钟最多 10 次）。".to_string();
        }

        let max = max_results.unwrap_or(5);

        // 检查缓存
        let cache_key = format!("{}|{}|{}", query, max, backend.unwrap_or("auto"));
        {
            let mut cache = self.cache.lock().unwrap();
            if let Some(cached) = cache.get(&cache_key) {
                return cached;
            }
        }

        let client_guard = self.client.lock().unwrap();
        let client = match client_guard.as_ref() {
            Some(c) => c,
            None => return "[search_client] HTTP 客户端未初始化，请先调用 init()".to_string(),
        };

        let result = match backend {
            Some("brave") => self.search_brave(client, query, max),
            Some("serper") => self.search_serper(client, query, max),
            Some("ddg") | Some("duckduckgo") => self.search_ddg(client, query, max),
            _ => {
                // Auto mode: try Brave -> Serper -> DDG
                let brave_result = self.search_brave(client, query, max);
                if !brave_result.starts_with("[brave]") {
                    brave_result
                } else {
                    let serper_result = self.search_serper(client, query, max);
                    if !serper_result.starts_with("[serper]") {
                        serper_result
                    } else {
                        self.search_ddg(client, query, max)
                    }
                }
            }
        };

        // 缓存结果
        {
            let mut cache = self.cache.lock().unwrap();
            cache.put(cache_key, result.clone());
        }

        result
    }

    /// 获取统计信息
    fn get_stats(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("ddg_count", self.ddg_count.load(Ordering::Relaxed))?;
            dict.set_item("brave_count", self.brave_count.load(Ordering::Relaxed))?;
            dict.set_item("serper_count", self.serper_count.load(Ordering::Relaxed))?;
            dict.set_item("rate_count", self.rate_count.load(Ordering::Relaxed))?;
            dict.set_item("enabled", self.is_enabled())?;
            Ok(dict.into())
        })
    }

    fn health(&self) -> &'static str {
        "search_client: operational (DDG + Brave + Serper, LRU cache, rate limited)"
    }
}

// ── 内部方法 (非 Python 接口) ──

impl SearchClient {
    fn search_brave(&self, client: &Client, query: &str, max: usize) -> String {
        let api_key = std::env::var("BRAVE_API_KEY").unwrap_or_default();
        if api_key.is_empty() {
            return "[brave] BRAVE_API_KEY 未设置".to_string();
        }

        self.brave_count.fetch_add(1, Ordering::Relaxed);

        match client
            .get("https://api.search.brave.com/res/v1/web/search")
            .header("Accept", "application/json")
            .header("Accept-Encoding", "gzip")
            .header("X-Subscription-Token", &api_key)
            .query(&[("q", query), ("count", &max.to_string())])
            .send()
        {
            Ok(resp) => match resp.json::<Value>() {
                Ok(v) => {
                    if let Some(web) = v["web"]["results"].as_array() {
                        return format_search_results(web, "Brave");
                    }
                    format_single_result(&v, "Brave", query)
                }
                Err(e) => format!("[brave] 解析失败: {}", e),
            },
            Err(e) => format!("[brave] 请求失败: {}", e),
        }
    }

    fn search_serper(&self, client: &Client, query: &str, max: usize) -> String {
        let api_key = std::env::var("SERPER_API_KEY").unwrap_or_default();
        if api_key.is_empty() {
            return "[serper] SERPER_API_KEY 未设置".to_string();
        }

        self.serper_count.fetch_add(1, Ordering::Relaxed);

        let body = serde_json::json!({"q": query, "num": max});

        match client
            .post("https://google.serper.dev/search")
            .header("X-API-KEY", &api_key)
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
        {
            Ok(resp) => match resp.json::<Value>() {
                Ok(v) => {
                    let organic = v["organic"].as_array();
                    let knowledge = v["knowledgeGraph"].as_object();
                    let answer = v["answerBox"].as_object();

                    let mut result = String::new();
                    if let Some(kg) = knowledge {
                        if let Some(title) = kg.get("title").and_then(|t| t.as_str()) {
                            result.push_str(&format!("📌 {}\n", title));
                        }
                        if let Some(desc) = kg.get("description").and_then(|d| d.as_str()) {
                            result.push_str(&format!("   {}\n\n", desc));
                        }
                    }
                    if let Some(ab) = answer {
                        if let Some(ans) = ab.get("answer").and_then(|a| a.as_str()) {
                            result.push_str(&format!("💡 {}\n\n", ans));
                        }
                    }
                    if let Some(org) = organic {
                        format_serper_results(&mut result, org);
                    }
                    if result.is_empty() {
                        return format!("[serper] 未找到结果: {}", query);
                    }
                    result
                }
                Err(e) => format!("[serper] 解析失败: {}", e),
            },
            Err(e) => format!("[serper] 请求失败: {}", e),
        }
    }

    fn search_ddg(&self, client: &Client, query: &str, max: usize) -> String {
        self.ddg_count.fetch_add(1, Ordering::Relaxed);

        // DuckDuckGo HTML search (API-free)
        let url = format!(
            "https://html.duckduckgo.com/html/?q={}",
            urlencoding(query)
        );
        match client.get(&url)
            .header("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            .send()
        {
            Ok(resp) => match resp.text() {
                Ok(html) => {
                    let results = parse_ddg_html(&html, max);
                    if results.is_empty() {
                        format!("[ddg] 未找到结果: {}", query)
                    } else {
                        let mut out = String::new();
                        for (i, (title, snippet, url)) in results.iter().enumerate() {
                            out.push_str(&format!(
                                "{}. {}\n   {}\n   {}\n\n",
                                i + 1, title, url, snippet
                            ));
                        }
                        out
                    }
                }
                Err(e) => format!("[ddg] 读取响应失败: {}", e),
            },
            Err(e) => format!("[ddg] 请求失败: {}", e),
        }
    }
}

/// URL 编码
fn urlencoding(s: &str) -> String {
    s.chars().map(|c| match c {
        'A'..='Z' | 'a'..='z' | '0'..='9' | '-' | '_' | '.' | '~' => c.to_string(),
        ' ' => "+".to_string(),
        _ => format!("%{:02X}", c as u32 as u8),
    }).collect()
}

/// 格式化搜索结果
fn format_search_results(results: &[Value], source: &str) -> String {
    let mut out = String::new();
    for (i, r) in results.iter().enumerate() {
        let title = r["title"].as_str().unwrap_or("无标题");
        let url = r["url"].as_str().unwrap_or("");
        let desc = r["description"].as_str().unwrap_or("");
        out.push_str(&format!("{}. {}\n   {}\n   {}\n\n", i + 1, title, url, desc));
    }
    if out.is_empty() {
        format!("[{}] 未找到结果", source)
    } else {
        out
    }
}

/// 格式化单个结果
fn format_single_result(v: &Value, source: &str, query: &str) -> String {
    if let Some(answer) = v["answer"].as_str() {
        return format!("[{}] {}", source, answer);
    }
    format!("[{}] 未找到结果: {}", source, query)
}

/// 格式化 Serper 结果
fn format_serper_results(out: &mut String, results: &[Value]) {
    for (i, r) in results.iter().enumerate() {
        let title = r["title"].as_str().unwrap_or("无标题");
        let link = r["link"].as_str().unwrap_or("");
        let snippet = r["snippet"].as_str().unwrap_or("");
        out.push_str(&format!("{}. {}\n   {}\n   {}\n\n", i + 1, title, link, snippet));
    }
}

/// 解析 DuckDuckGo HTML 搜索结果
fn parse_ddg_html(html: &str, max: usize) -> Vec<(String, String, String)> {
    let mut results = Vec::new();

    // 简单解析 DDG HTML 结果
    // 查找 class="result" 的 div
    let mut current_title = String::new();
    let mut current_snippet = String::new();
    let mut current_url = String::new();
    let mut in_title = false;
    let mut in_snippet = false;

    for line in html.lines() {
        let line_trimmed = line.trim();

        if line_trimmed.contains("result__title") || line_trimmed.contains("class=\"result__a\"") {
            in_title = true;
            current_title.clear();
            current_snippet.clear();
            current_url.clear();
        }

        if in_title {
            if let Some(start) = line_trimmed.find("href=\"") {
                let after_href = &line_trimmed[start + 6..];
                if let Some(end) = after_href.find('"') {
                    current_url = after_href[..end].to_string();
                }
            }
            if let Some(start) = line_trimmed.find('>') {
                let after = &line_trimmed[start + 1..];
                if !after.contains("class=") {
                    current_title.push_str(after);
                    current_title.push(' ');
                }
            }
            if line_trimmed.contains("</a>") {
                in_title = false;
                in_snippet = true;
                current_title = current_title.trim().to_string();
                // Remove HTML tags
                current_title = strip_html(&current_title);
            }
        }

        if in_snippet {
            if line_trimmed.contains("result__snippet") {
                if let Some(start) = line_trimmed.find('>') {
                    let after = &line_trimmed[start + 1..];
                    current_snippet.push_str(after);
                    current_snippet.push(' ');
                }
            }
            if line_trimmed.contains("</div>") || line_trimmed.contains("</td>") {
                in_snippet = false;
                if !current_title.is_empty() {
                    current_snippet = strip_html(&current_snippet);
                    results.push((
                        current_title.clone(),
                        current_snippet.trim().to_string(),
                        current_url.clone(),
                    ));
                    if results.len() >= max {
                        break;
                    }
                }
            }
        }
    }

    results
}

/// 去除 HTML 标签
fn strip_html(s: &str) -> String {
    let mut result = String::new();
    let mut in_tag = false;
    for ch in s.chars() {
        match ch {
            '<' => in_tag = true,
            '>' => in_tag = false,
            _ if !in_tag => result.push(ch),
            _ => {}
        }
    }
    result.trim().to_string()
}
