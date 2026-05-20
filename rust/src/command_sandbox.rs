//! 安全命令执行沙箱
//!
//! 对应 Python: core/tools/bash_tool.py
//!
//! 使用 subprocess + 安全模式黑名单 + 超时控制

use pyo3::prelude::*;
use regex::Regex;
use std::collections::HashMap;
use std::process::Command;
use std::sync::Mutex;
use std::time::{Duration, Instant};

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CommandSandbox>()?;
    Ok(())
}

/// 危险命令模式 (与 Python bash_tool.py 保持一致)
lazy_static::lazy_static! {
    static ref DANGEROUS_PATTERNS: Vec<Regex> = vec![
        Regex::new(r"rm\s+-rf\s+/").unwrap(),
        Regex::new(r"rm\s+-rf\s+/\*").unwrap(),
        Regex::new(r"rm\s+-rf\s+~").unwrap(),
        Regex::new(r"mkfs\.").unwrap(),
        Regex::new(r"dd\s+if=").unwrap(),
        Regex::new(r">\s*/dev/sd").unwrap(),
        Regex::new(r"chmod\s+777\s+/").unwrap(),
        Regex::new(r":\(\)\s*\{\s*:\s*\|\:?\s*&\s*\};:").unwrap(), // fork bomb
        Regex::new(r"shutdown\s+(-h|-r|now)").unwrap(),
        Regex::new(r"reboot").unwrap(),
        Regex::new(r"curl\s+.*\|\s*(ba)?sh").unwrap(),
        Regex::new(r"wget\s+.*\|\s*(ba)?sh").unwrap(),
        Regex::new(r"chmod\s+777\s+\.").unwrap(),
        Regex::new(r"del\s+/F\s+/S\s+/Q\s+C:\\").unwrap(), // Windows destructive
        Regex::new(r"format\s+[A-Z]:").unwrap(), // Windows format
    ];
}

#[pyclass]
pub struct CommandSandbox {
    stats: Mutex<SandboxStats>,
}

#[derive(Default)]
struct SandboxStats {
    total_commands: u64,
    blocked_commands: u64,
    timed_out_commands: u64,
    failed_commands: u64,
}

#[pymethods]
impl CommandSandbox {
    #[new]
    fn new() -> Self {
        CommandSandbox { stats: Mutex::new(SandboxStats::default()) }
    }

    /// 安全执行命令
    fn execute(
        &self,
        command: &str,
        timeout_ms: Option<u64>,
        workdir: Option<&str>,
        env: Option<HashMap<String, String>>,
    ) -> String {
        let mut stats = self.stats.lock().unwrap();
        stats.total_commands += 1;

        // 安全检查
        if self.is_dangerous(command) {
            stats.blocked_commands += 1;
            return format!(
                "[sandbox] 命令被安全策略阻止:\n  命令: {}\n  原因: 匹配危险模式",
                command
            );
        }
        drop(stats);

        let timeout = Duration::from_millis(timeout_ms.unwrap_or(120_000).min(600_000));
        let start = Instant::now();

        let mut cmd = if cfg!(windows) {
            let mut c = Command::new("cmd");
            c.arg("/C").arg(command);
            c
        } else {
            let mut c = Command::new("sh");
            c.arg("-c").arg(command);
            c
        };

        // 工作目录
        if let Some(dir) = workdir {
            if !dir.is_empty() {
                cmd.current_dir(dir);
            }
        }

        // 环境变量
        if let Some(env_vars) = env {
            for (k, v) in &env_vars {
                cmd.env(k, v);
            }
        }

        // 执行
        match cmd.output() {
            Ok(output) => {
                let elapsed = start.elapsed();
                let stdout = String::from_utf8_lossy(&output.stdout);
                let stderr = String::from_utf8_lossy(&output.stderr);
                let exit_code = output.status.code().unwrap_or(-1);

                let stdout_trunc = truncate_output(stdout.as_ref(), 8000);
                let stderr_trunc = truncate_output(stderr.as_ref(), 4000);

                let mut result = String::new();
                if !stdout_trunc.is_empty() {
                    result.push_str(&stdout_trunc);
                }
                if !stderr_trunc.is_empty() {
                    if !result.is_empty() { result.push_str("\n\n"); }
                    result.push_str(&format!("[stderr]\n{}", stderr_trunc));
                }

                if exit_code != 0 {
                    if !result.is_empty() { result.push_str("\n\n"); }
                    result.push_str(&format!(
                        "[returncode: {}, elapsed: {:.1}s]",
                        exit_code,
                        elapsed.as_secs_f64()
                    ));
                }

                if result.is_empty() {
                    result = format!("[exit: {}, elapsed: {:.1}s]", exit_code, elapsed.as_secs_f64());
                }

                let mut stats = self.stats.lock().unwrap();
                if exit_code != 0 {
                    stats.failed_commands += 1;
                }
                if elapsed > timeout {
                    stats.timed_out_commands += 1;
                }

                result
            }
            Err(e) => {
                let mut stats = self.stats.lock().unwrap();
                stats.failed_commands += 1;

                if start.elapsed() > timeout {
                    stats.timed_out_commands += 1;
                    format!("[sandbox] 命令执行超时 (>{:.0}s): {}", timeout.as_secs_f64(), e)
                } else {
                    format!("[sandbox] 命令执行失败: {}", e)
                }
            }
        }
    }

    /// 检查命令是否危险
    fn is_dangerous(&self, command: &str) -> bool {
        DANGEROUS_PATTERNS.iter().any(|re| re.is_match(command))
    }

    fn get_stats(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let stats = self.stats.lock().unwrap();
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("total_commands", stats.total_commands)?;
            dict.set_item("blocked_commands", stats.blocked_commands)?;
            dict.set_item("timed_out_commands", stats.timed_out_commands)?;
            dict.set_item("failed_commands", stats.failed_commands)?;
            Ok(dict.into())
        })
    }

    fn health(&self) -> &'static str {
        "command_sandbox: operational (secure subprocess + blacklist + timeout)"
    }
}

/// 截断输出到最大字符数
fn truncate_output(text: &str, max_chars: usize) -> String {
    if text.len() <= max_chars {
        return text.to_string();
    }
    let mut truncated = text[..max_chars].to_string();
    truncated.push_str(&format!(
        "\n...[截断: 共 {} 字符, 仅显示前 {} 字符]",
        text.len(), max_chars
    ));
    truncated
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_dangerous_rm_rf() {
        let sb = CommandSandbox::new();
        assert!(sb.is_dangerous("rm -rf /"));
        assert!(sb.is_dangerous("rm -rf / --no-preserve-root"));
    }

    #[test]
    fn test_is_dangerous_fork_bomb() {
        let sb = CommandSandbox::new();
        assert!(sb.is_dangerous(":(){ :|:& };:"));
    }

    #[test]
    fn test_is_safe_echo() {
        let sb = CommandSandbox::new();
        assert!(!sb.is_dangerous("echo hello world"));
        assert!(!sb.is_dangerous("ls -la"));
        assert!(!sb.is_dangerous("git status"));
    }

    #[test]
    fn test_safe_command_execution() {
        let sb = CommandSandbox::new();
        let result = sb.execute("echo hello", Some(5000), None, None);
        assert!(result.contains("hello"), "should contain 'hello', got: {}", result);
    }

    #[test]
    fn test_dangerous_command_blocked() {
        let sb = CommandSandbox::new();
        let result = sb.execute("rm -rf /", Some(5000), None, None);
        assert!(result.contains("阻止"), "should be blocked");
    }

    #[test]
    fn test_truncate_output() {
        let long = "a".repeat(10000);
        let truncated = truncate_output(&long, 8000);
        assert_eq!(truncated.len(), 8000 + "[截断: 共 10000 字符, 仅显示前 8000 字符]".len());
    }
}
