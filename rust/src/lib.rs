//! SEAI Rust 底层引擎 — PyO3 入口
//!
//! 模块结构：
//! - event_bus: VecDeque + Mutex 消息缓冲
//! - memory_engine: 余弦相似度 + JSONL 持久化
//! - knowledge_graph: petgraph 图引擎
//! - sandbox: 递归下降安全求值器
//! - circuit_breaker: AtomicU32 CAS 零锁状态机
//! - http_client: reqwest + 指数退避 + 多端点 fallback
//! - context_manager: 启发式 token 估算 + 压缩决策
//! - file_ops: ripgrep + 原子文件编辑 + glob 遍历
//! - tokenizer: tiktoken 兼容 BPE 估算器
//! - search_client: 多后端搜索 (Brave/Serper/DDG)
//! - command_sandbox: 安全子进程执行沙箱

use pyo3::prelude::*;

// ── 子模块声明 ──────────────────────────────

pub mod event_bus;
pub mod memory_engine;
pub mod knowledge_graph;
pub mod sandbox;
pub mod circuit_breaker;
pub mod http_client;
pub mod context_manager;
pub mod file_ops;
pub mod tokenizer;
pub mod search_client;
pub mod command_sandbox;

// ── 顶级工具函数 ────────────────────────────

/// 健康检查 — 验证 Rust 引擎可用
#[pyfunction]
fn health_check() -> String {
    format!("seai._rust_core v{} — all systems operational", env!("CARGO_PKG_VERSION"))
}

/// 内存安全 add — 用于验证 PyO3 集成
#[pyfunction]
fn add(a: i64, b: i64) -> i64 {
    a + b
}

// ── 模块注册 ────────────────────────────────

/// SEAI Rust 引擎 Python 模块
#[pymodule]
#[pyo3(name = "_rust_core")]
fn _rust_core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(health_check, m)?)?;
    m.add_function(wrap_pyfunction!(add, m)?)?;

    // 注册子模块
    event_bus::register(m)?;
    memory_engine::register(m)?;
    knowledge_graph::register(m)?;
    sandbox::register(m)?;
    circuit_breaker::register(m)?;
    http_client::register(m)?;
    context_manager::register(m)?;
    file_ops::register(m)?;
    tokenizer::register(m)?;
    search_client::register(m)?;
    command_sandbox::register(m)?;

    Ok(())
}
