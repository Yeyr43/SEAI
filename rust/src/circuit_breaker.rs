//! 熔断器 — AtomicU32 零锁状态机
//!
//! 对应 Python: core/circuit_breaker.py
//!
//! 状态转换: CLOSED → (failures >= threshold) → OPEN → (timeout elapsed) → HALF_OPEN
//! HALF_OPEN + success → CLOSED | HALF_OPEN + failure → OPEN

use pyo3::prelude::*;
use std::sync::atomic::{AtomicU32, AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<CircuitBreaker>()?;
    Ok(())
}

const CLOSED: u32 = 0;
const OPEN: u32 = 1;
const HALF_OPEN: u32 = 2;

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis() as u64
}

#[pyclass]
pub struct CircuitBreaker {
    state: AtomicU32,
    failure_count: AtomicU32,
    success_count: AtomicU32,
    threshold: u32,
    recovery_timeout_ms: u64,
    last_state_change_ms: AtomicU64,
}

#[pymethods]
impl CircuitBreaker {
    #[new]
    fn new(threshold: Option<u32>, recovery_timeout_ms: Option<u64>) -> Self {
        CircuitBreaker {
            state: AtomicU32::new(CLOSED),
            failure_count: AtomicU32::new(0),
            success_count: AtomicU32::new(0),
            threshold: threshold.unwrap_or(5),
            recovery_timeout_ms: recovery_timeout_ms.unwrap_or(30000),
            last_state_change_ms: AtomicU64::new(now_ms()),
        }
    }

    fn can_execute(&self) -> bool {
        let state = self.state.load(Ordering::Acquire);
        match state {
            CLOSED => true,
            HALF_OPEN => true,
            OPEN => {
                let elapsed = now_ms() - self.last_state_change_ms.load(Ordering::Acquire);
                if elapsed >= self.recovery_timeout_ms {
                    // CAS to HALF_OPEN
                    if self.state.compare_exchange(
                        OPEN, HALF_OPEN, Ordering::AcqRel, Ordering::Acquire
                    ).is_ok() {
                        self.last_state_change_ms.store(now_ms(), Ordering::Release);
                        return true;
                    }
                    // Another thread changed state, re-check
                    self.state.load(Ordering::Acquire) != OPEN
                } else {
                    false
                }
            }
            _ => false,
        }
    }

    fn on_success(&self) {
        if self.state.load(Ordering::Acquire) != CLOSED {
            self.state.store(CLOSED, Ordering::Release);
            self.last_state_change_ms.store(now_ms(), Ordering::Release);
        }
        self.failure_count.store(0, Ordering::Release);
        self.success_count.fetch_add(1, Ordering::Release);
    }

    fn on_failure(&self) {
        let count = self.failure_count.fetch_add(1, Ordering::Release) + 1;
        if count >= self.threshold {
            self.state.store(OPEN, Ordering::Release);
            self.last_state_change_ms.store(now_ms(), Ordering::Release);
        }
    }

    /// 重置熔断器到 CLOSED 状态
    fn reset(&self) {
        self.state.store(CLOSED, Ordering::Release);
        self.failure_count.store(0, Ordering::Release);
        self.last_state_change_ms.store(now_ms(), Ordering::Release);
    }

    fn get_state(&self) -> &'static str {
        // Also check for auto-recovery (only changes state if OPEN → HALF_OPEN is eligible)
        self.can_execute();
        match self.state.load(Ordering::Acquire) {
            CLOSED => "CLOSED",
            OPEN => "OPEN",
            HALF_OPEN => "HALF_OPEN",
            _ => "UNKNOWN",
        }
    }

    fn get_stats(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("state", self.get_state())?;
            dict.set_item("failures", self.failure_count.load(Ordering::Acquire))?;
            dict.set_item("successes", self.success_count.load(Ordering::Acquire))?;
            dict.set_item("threshold", self.threshold)?;
            dict.set_item("recovery_timeout_ms", self.recovery_timeout_ms)?;
            let elapsed = now_ms() - self.last_state_change_ms.load(Ordering::Acquire);
            dict.set_item("ms_since_state_change", elapsed)?;
            Ok(dict.into())
        })
    }

    fn health(&self) -> &'static str {
        "circuit_breaker: operational (AtomicU32 CAS state machine)"
    }
}
