//! 文件操作引擎 — ripgrep + 原子编辑 + glob 遍历
//!
//! 对应 Python: core/tools/grep_tool.py, edit_tool.py, glob_tool.py

use pyo3::prelude::*;
use std::path::PathBuf;
use std::process::Command;
use std::sync::Mutex;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<FileOps>()?;
    Ok(())
}

#[pyclass]
pub struct FileOps {
    stats: Mutex<FileOpsStats>,
}

#[derive(Default)]
struct FileOpsStats {
    grep_calls: u64,
    edit_calls: u64,
    glob_calls: u64,
}

#[pymethods]
impl FileOps {
    #[new]
    fn new() -> Self {
        FileOps { stats: Mutex::new(FileOpsStats::default()) }
    }

    /// ripgrep 搜索 — 调用 rg 二进制，解析 --json 输出
    fn grep(
        &self,
        pattern: &str,
        path: &str,
        glob_filter: Option<&str>,
        ignore_case: Option<bool>,
        head_limit: Option<usize>,
        before: Option<usize>,
        after: Option<usize>,
        multiline: Option<bool>,
    ) -> String {
        let mut stats = self.stats.lock().unwrap();
        stats.grep_calls += 1;
        drop(stats);

        let mut cmd = Command::new("rg");
        cmd.arg("--no-heading")
            .arg("--with-filename")
            .arg("--line-number")
            .arg("--color=never")
            .arg("--json");

        if ignore_case.unwrap_or(false) {
            cmd.arg("--ignore-case");
        }
        if multiline.unwrap_or(false) {
            cmd.arg("--multiline").arg("--multiline-dotall");
        }
        if let Some(b) = before {
            if b > 0 { cmd.arg(format!("-B{}", b)); }
        }
        if let Some(a) = after {
            if a > 0 { cmd.arg(format!("-A{}", a)); }
        }
        if let Some(g) = glob_filter {
            if !g.is_empty() { cmd.arg("--glob").arg(g); }
        }

        cmd.arg("--").arg(pattern).arg(path);

        let limit = head_limit.unwrap_or(50);
        let output = match cmd.output() {
            Ok(o) => o,
            Err(e) => return format!("[file_ops] rg 执行失败: {}", e),
        };

        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut results: Vec<&str> = stdout.lines().filter(|line| {
            !line.trim().is_empty()
        }).collect();

        if results.len() > limit {
            results.truncate(limit);
        }

        let result = results.join("\n");
        if result.is_empty() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            if !stderr.is_empty() {
                return format!("[rg stderr]\n{}", stderr);
            }
            return String::from("[file_ops] 无匹配结果");
        }
        result
    }

    /// 原子文件编辑 — 读文件，替换字符串，写临时文件，原子重命名
    fn edit_file(
        &self,
        file_path: &str,
        old_string: &str,
        new_string: &str,
        replace_all: Option<bool>,
    ) -> String {
        let mut stats = self.stats.lock().unwrap();
        stats.edit_calls += 1;
        drop(stats);

        let path = PathBuf::from(file_path);
        let content = match std::fs::read_to_string(&path) {
            Ok(c) => c,
            Err(e) => return format!("[file_ops] 读取文件失败: {}", e),
        };

        let replace_all = replace_all.unwrap_or(false);
        let (result, count) = if replace_all {
            (content.replace(old_string, new_string), content.matches(old_string).count())
        } else {
            let matches: Vec<(usize, &str)> = content.match_indices(old_string).collect();
            if matches.is_empty() {
                return format!("[file_ops] 未找到匹配的字符串: {}", old_string);
            }
            if matches.len() > 1 {
                let lines: Vec<String> = matches.iter().take(5).map(|(pos, _)| {
                    let line = content[..*pos].matches('\n').count() + 1;
                    format!("  第 {} 行", line)
                }).collect();
                return format!(
                    "[file_ops] 找到 {} 处匹配，请缩小范围:\n{}",
                    matches.len(),
                    lines.join("\n")
                );
            }
            (content.replacen(old_string, new_string, 1), 1)
        };

        // 原子写入：先写临时文件，再重命名
        let tmp_path = path.with_extension(
            format!("{}.tmp", path.extension().map(|e| e.to_string_lossy().to_string()).unwrap_or_default())
        );
        if let Err(e) = std::fs::write(&tmp_path, &result) {
            return format!("[file_ops] 写入临时文件失败: {}", e);
        }
        if let Err(e) = std::fs::rename(&tmp_path, &path) {
            let _ = std::fs::remove_file(&tmp_path);
            return format!("[file_ops] 重命名失败: {}", e);
        }

        format!("[file_ops] 已编辑 {}，替换了 {} 处", file_path, count)
    }

    /// 递归 glob 遍历 — 使用 walkdir 实现
    fn glob(
        &self,
        pattern: &str,
        path: &str,
        max_results: Option<usize>,
    ) -> String {
        let mut stats = self.stats.lock().unwrap();
        stats.glob_calls += 1;
        drop(stats);

        let search_root = PathBuf::from(path);
        if !search_root.exists() {
            return format!("[file_ops] 路径不存在: {}", path);
        }

        let max = max_results.unwrap_or(200);
        let mut results = Vec::new();

        // 转换 glob pattern 为通配符匹配
        // 支持 **, *, ? 模式
        // 先收集所有文件
        for entry in walkdir::WalkDir::new(&search_root)
            .follow_links(false)
            .into_iter()
            .filter_map(|e| e.ok())
        {
            if results.len() >= max {
                break;
            }
            if entry.file_type().is_file() {
                let rel_path = entry.path().strip_prefix(&search_root)
                    .unwrap_or(entry.path());
                let path_str = rel_path.to_string_lossy().replace('\\', "/");

                // 简单 glob 匹配
                if glob_match(pattern, &path_str) {
                    let size = entry.metadata()
                        .map(|m| m.len())
                        .unwrap_or(0);
                    let size_kb = size / 1024;
                    results.push(format!("{} ({:.1} KB)", path_str, size_kb as f64));
                }
            }
        }

        if results.is_empty() {
            return format!("[file_ops] 未找到匹配 '{}' 的文件", pattern);
        }

        results.truncate(max);
        results.join("\n")
    }

    fn health(&self) -> &'static str {
        "file_ops: operational (ripgrep + atomic edit + walkdir glob)"
    }
}

/// 简单 glob 匹配 — 支持 *, **, ?
fn glob_match(pattern: &str, path: &str) -> bool {
    let parts: Vec<&str> = pattern.split('/').collect();
    let path_parts: Vec<&str> = path.split('/').collect();

    let mut pi = 0;
    let mut pp = 0;
    let mut backtrack_pi = 0;
    let mut backtrack_pp = 0;
    let mut in_star = false;

    while pi < path_parts.len() {
        if pp < parts.len() && parts[pp] == "**" {
            // ** 匹配零个或多个路径段
            if pp + 1 >= parts.len() {
                return true; // ** at end matches everything
            }
            pp += 1;
            backtrack_pp = pp;
            backtrack_pi = pi;
            in_star = true;
        } else if pp < parts.len() && single_glob_match(parts[pp], path_parts[pi]) {
            pi += 1;
            pp += 1;
        } else if in_star {
            backtrack_pi += 1;
            pi = backtrack_pi;
            pp = backtrack_pp;
            if pi >= path_parts.len() {
                return false;
            }
        } else {
            return false;
        }
    }

    // 消耗剩余的 **
    while pp < parts.len() && parts[pp] == "**" {
        pp += 1;
    }

    pi == path_parts.len() && pp == parts.len()
}

/// 单段 glob 匹配 — 支持 * 和 ?
fn single_glob_match(pattern: &str, s: &str) -> bool {
    let p: Vec<char> = pattern.chars().collect();
    let t: Vec<char> = s.chars().collect();
    let pn = p.len();
    let tn = t.len();

    // DP: dp[i][j] = p[..i] matches t[..j]
    let mut dp = vec![vec![false; tn + 1]; pn + 1];
    dp[0][0] = true;

    for i in 1..=pn {
        if p[i - 1] == '*' {
            dp[i][0] = dp[i - 1][0];
        }
    }

    for i in 1..=pn {
        for j in 1..=tn {
            match p[i - 1] {
                '*' => {
                    dp[i][j] = dp[i - 1][j] || dp[i][j - 1];
                }
                '?' => {
                    dp[i][j] = dp[i - 1][j - 1];
                }
                pc => {
                    dp[i][j] = dp[i - 1][j - 1] && pc == t[j - 1];
                }
            }
        }
    }

    dp[pn][tn]
}
