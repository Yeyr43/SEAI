//! 快速 Token 计数器 — tiktoken 兼容的 BPE 估算
//!
//! 对应 Python: core/context_manager.py (token 估算部分)
//!
//! 使用启发式算法近似 cl100k_base 编码器行为

use pyo3::prelude::*;
use std::sync::Mutex;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustTokenizer>()?;
    Ok(())
}

/// 字符类型分类 — 用于启发式 token 估算
fn char_type(ch: char) -> u8 {
    if ch.is_whitespace() { 0 }
    else if ch.is_ascii_alphabetic() { 1 }
    else if ch.is_ascii_digit() { 2 }
    else if ch.is_ascii_punctuation() { 3 }
    else { 4 } // CJK / emoji / other wide chars
}

/// 启发式 token 计数（近似 cl100k_base）
fn count_chars(text: &str) -> usize {
    if text.is_empty() { return 0; }

    let chars: Vec<char> = text.chars().collect();
    let len = chars.len();
    let mut tokens: f64 = 0.0;
    let mut i = 0;

    while i < len {
        let ch = chars[i];
        match char_type(ch) {
            0 => {
                // whitespace run: ~1 token per 4 chars
                let start = i;
                while i < len && char_type(chars[i]) == 0 { i += 1; }
                let run = i - start;
                tokens += (run as f64 * 0.25).max(1.0);
            }
            1 => {
                // alphabetic word: ~1 token per 4 chars
                let start = i;
                while i < len && char_type(chars[i]) == 1 { i += 1; }
                let word_len = i - start;
                tokens += (word_len as f64 / 4.0).max(1.0).ceil();
            }
            2 => {
                // number: ~1 token per 3 chars
                let start = i;
                while i < len && (char_type(chars[i]) == 2 || chars[i] == '.') { i += 1; }
                let num_len = i - start;
                tokens += (num_len as f64 / 3.0).max(1.0).ceil();
            }
            3 => {
                // punctuation: 1 token per char
                i += 1;
                tokens += 1.0;
            }
            _ => {
                // CJK/emoji: ~1.5 tokens per char
                i += 1;
                tokens += 1.5;
            }
        }
    }

    tokens as usize
}

#[pyclass]
pub struct RustTokenizer {
    stats: Mutex<TokenizerStats>,
}

#[derive(Default)]
struct TokenizerStats {
    total_texts: u64,
    total_tokens: u64,
}

#[pymethods]
impl RustTokenizer {
    #[new]
    fn new() -> Self {
        RustTokenizer { stats: Mutex::new(TokenizerStats::default()) }
    }

    /// 计算文本 token 数
    /// model 参数可选: "claude", "gpt-4", "gpt-3.5", "deepseek" 等
    fn count_tokens(&self, text: &str, model: Option<&str>) -> usize {
        let model = model.unwrap_or("claude");
        let count = match model {
            "claude" | "claude-3" | "claude-4" | "claude-opus" | "claude-sonnet" | "claude-haiku" => {
                count_claude(text)
            }
            "gpt-4" | "gpt-4o" | "gpt-4-turbo" | "gpt-3.5" | "gpt-3.5-turbo" | "o1" | "o3" | "o4" => {
                count_chars(text) // cl100k_base compatible
            }
            "deepseek" | "deepseek-v3" | "deepseek-r1" => {
                count_deepseek(text)
            }
            "gemini" | "gemini-pro" | "gemini-2.5" => {
                (text.len() as f64 * 0.25) as usize
            }
            _ => text.len() / 4,
        };

        let mut stats = self.stats.lock().unwrap();
        stats.total_texts += 1;
        stats.total_tokens += count as u64;

        count
    }

    /// 批量计算消息列表的 token 数
    fn count_messages(&self, messages_json: &str) -> PyResult<usize> {
        let total: usize = if let Ok(arr) = serde_json::from_str::<Vec<serde_json::Value>>(messages_json) {
            arr.iter().map(|msg| {
                let role = msg["role"].as_str().unwrap_or("");
                let content = msg["content"].as_str().unwrap_or("");
                count_chars(role) + count_chars(content) + 4
            }).sum()
        } else {
            count_chars(messages_json)
        };
        Ok(total)
    }

    /// 截断文本到目标 token 数
    fn truncate_to_tokens(&self, text: &str, max_tokens: usize) -> String {
        let mut result = String::new();
        let mut current_tokens = 0usize;

        for ch in text.chars() {
            let token_cost = match char_type(ch) {
                4 => 2, // CJK: ~1.5 -> ceil to 2
                _ => 1,
            };
            if current_tokens + token_cost > max_tokens {
                break;
            }
            result.push(ch);
            current_tokens += token_cost;
        }

        if result.len() < text.len() {
            result.push_str("…");
        }
        result
    }

    fn get_stats(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let stats = self.stats.lock().unwrap();
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("total_texts", stats.total_texts)?;
            dict.set_item("total_tokens", stats.total_tokens)?;
            let avg = if stats.total_texts > 0 {
                stats.total_tokens / stats.total_texts
            } else { 0 };
            dict.set_item("avg_tokens_per_text", avg)?;
            Ok(dict.into())
        })
    }

    fn health(&self) -> &'static str {
        "tokenizer: operational (heuristic BPE + model-aware)"
    }
}

/// Claude 模型 token 估算 (更激进的 BPE)
fn count_claude(text: &str) -> usize {
    // Claude 使用特殊的 tokenizer，但启发式估算接近
    let base = count_chars(text);
    // Claude 对代码/结构化文本的分词效率更高
    (base as f64 * 0.95) as usize
}

/// DeepSeek 模型 token 估算
fn count_deepseek(text: &str) -> usize {
    // DeepSeek 使用类似 cl100k 的分词器，但对中文更友好
    let chars: Vec<char> = text.chars().collect();
    let cjk_ratio = chars.iter().filter(|c| char_type(**c) == 4).count() as f64 / chars.len().max(1) as f64;

    if cjk_ratio > 0.3 {
        // 高 CJK 占比：DeepSeek 对中文分词更高效
        (count_chars(text) as f64 * 0.85) as usize
    } else {
        count_chars(text)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_count_english() {
        let t = RustTokenizer::new();
        let n = t.count_tokens("Hello, world! This is a test.", Some("gpt-4"));
        assert!(n > 0, "should count > 0 tokens");
        assert!(n < 20, "should be < 20 for short English text");
    }

    #[test]
    fn test_count_cjk() {
        let t = RustTokenizer::new();
        let n = t.count_tokens("你好世界这是一个测试", Some("claude"));
        assert!(n > 0, "CJK tokens should be > 0");
        // CJK: ~1.5 tokens/char * 10 chars = ~15
        assert!(n >= 10, "CJK should have at least 10 tokens for 10 chars");
    }

    #[test]
    fn test_empty() {
        let t = RustTokenizer::new();
        assert_eq!(t.count_tokens("", None), 0);
    }

    #[test]
    fn test_model_variants() {
        let t = RustTokenizer::new();
        let text = "Hello world";
        let gpt = t.count_tokens(text, Some("gpt-4"));
        let claude = t.count_tokens(text, Some("claude"));
        let deepseek = t.count_tokens(text, Some("deepseek"));
        // All should return non-zero
        assert!(gpt > 0);
        assert!(claude > 0);
        assert!(deepseek > 0);
    }

    #[test]
    fn test_truncate() {
        let t = RustTokenizer::new();
        let long = "a".repeat(100);
        let truncated = t.truncate_to_tokens(&long, 10);
        assert!(truncated.len() <= long.len());
        assert!(truncated.ends_with('…'));
    }
}
