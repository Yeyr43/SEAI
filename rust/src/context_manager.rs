//! 上下文管理器 — Token 计数 + 压缩决策
//!
//! 对应 Python: core/context_manager.py
//!
//! 使用启发式算法估算 token 数量（近似 cl100k_base 行为）

use pyo3::prelude::*;
use std::sync::Mutex;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<ContextManager>()?;
    Ok(())
}

/// 字符类型分类
fn char_type(ch: char) -> u8 {
    if ch.is_whitespace() { 0 }
    else if ch.is_ascii_alphabetic() { 1 }
    else if ch.is_ascii_digit() { 2 }
    else if ch.is_ascii_punctuation() { 3 }
    else { 4 } // CJK / emoji / other wide chars
}

/// 启发式 token 计数（近似 cl100k_base）
/// 规则：
/// - CJK 字符：~1.5 token/char
/// - 英文单词：~1.3 token/word
/// - 代码符号：~1 token/symbol cluster
/// - 空格/换行：~0.3 token/char (merge into runs)
fn estimate_tokens(text: &str) -> usize {
    if text.is_empty() {
        return 0;
    }

    let mut tokens: f64 = 0.0;
    let chars: Vec<char> = text.chars().collect();
    let len = chars.len();
    let mut i = 0;

    while i < len {
        let ch = chars[i];
        let ct = char_type(ch);

        match ct {
            0 => {
                // whitespace: count ~1 token per 4 whitespace chars
                let start = i;
                while i < len && char_type(chars[i]) == 0 { i += 1; }
                let run = i - start;
                tokens += (run as f64 * 0.25).max(1.0);
            }
            1 => {
                // alphabetic: group into word
                let start = i;
                while i < len && char_type(chars[i]) == 1 { i += 1; }
                let word_len = i - start;
                // Rough BPE: ~1 token per 4 chars for English
                tokens += (word_len as f64 / 4.0).max(1.0).ceil();
            }
            2 => {
                // digits: likely a number
                let start = i;
                while i < len && (char_type(chars[i]) == 2 || chars[i] == '.') { i += 1; }
                let num_len = i - start;
                tokens += (num_len as f64 / 3.0).max(1.0).ceil();
            }
            3 => {
                // punctuation/symbols
                if ch == '"' || ch == '\'' {
                    // string delimiters
                    i += 1;
                    tokens += 1.0;
                } else {
                    i += 1;
                    tokens += 1.0;
                }
            }
            _ => {
                // CJK / emoji / other: ~1.5 tokens per char
                i += 1;
                tokens += 1.5;
            }
        }
    }

    tokens as usize
}

#[pyclass]
pub struct ContextManager {
    stats: Mutex<ContextStats>,
}

#[derive(Default)]
struct ContextStats {
    total_counted: u64,
    total_tokens: u64,
}

#[pymethods]
impl ContextManager {
    #[new]
    fn new() -> Self {
        ContextManager {
            stats: Mutex::new(ContextStats::default()),
        }
    }

    /// 估算文本的 token 数量
    fn count_tokens(&self, text: &str, model: Option<&str>) -> usize {
        let model = model.unwrap_or("claude");
        let count = match model {
            "claude" | "claude-3" | "claude-4" => estimate_tokens(text),
            "gpt-4" | "gpt-4o" | "gpt-3.5" => estimate_tokens(text),
            _ => text.len() / 4,
        };

        let mut stats = self.stats.lock().unwrap();
        stats.total_counted += 1;
        stats.total_tokens += count as u64;

        count
    }

    /// 批量估算消息列表的 token 数
    fn count_messages(&self, messages_json: &str) -> PyResult<usize> {
        let total: usize = if let Ok(arr) = serde_json::from_str::<Vec<serde_json::Value>>(messages_json) {
            arr.iter()
                .map(|msg| {
                    let role = msg["role"].as_str().unwrap_or("");
                    let content = msg["content"].as_str().unwrap_or("");
                    let role_tokens = estimate_tokens(role);
                    let content_tokens = estimate_tokens(content);
                    role_tokens + content_tokens + 4 // overhead per message
                })
                .sum()
        } else {
            estimate_tokens(messages_json)
        };
        Ok(total)
    }

    /// 判断是否需要压缩（超过 80% 阈值）
    fn should_compress(&self, token_count: usize, context_limit: usize) -> bool {
        let threshold = (context_limit as f64 * 0.8) as usize;
        token_count > threshold
    }

    /// 获取压缩建议级别 (0=none, 1=light, 2=aggressive)
    fn compression_level(&self, token_count: usize, context_limit: usize) -> u8 {
        let ratio = token_count as f64 / context_limit as f64;
        if ratio < 0.5 {
            0
        } else if ratio < 0.8 {
            1
        } else {
            2
        }
    }

    /// 估算压缩后的 token 节省量
    fn estimate_savings(&self, token_count: usize, level: u8) -> usize {
        match level {
            0 => 0,
            1 => (token_count as f64 * 0.3) as usize,
            2 => (token_count as f64 * 0.5) as usize,
            _ => (token_count as f64 * 0.5) as usize,
        }
    }

    fn get_stats(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let stats = self.stats.lock().unwrap();
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("total_counted", stats.total_counted)?;
            dict.set_item("total_tokens", stats.total_tokens)?;
            let avg = if stats.total_counted > 0 {
                stats.total_tokens as f64 / stats.total_counted as f64
            } else {
                0.0
            };
            dict.set_item("avg_tokens_per_call", avg as usize)?;
            Ok(dict.into())
        })
    }

    fn health(&self) -> &'static str {
        "context_manager: operational (heuristic token estimator)"
    }
}
