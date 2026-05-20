//! 事件总线 — VecDeque 消息缓冲 + Mutex 并发
//!
//! 对应 Python: core/event_bus/bus.py

use pyo3::prelude::*;
use std::collections::{HashMap, VecDeque};
use std::sync::Mutex;

const MAX_CHANNEL_MESSAGES: usize = 1024;

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<RustEventBus>()?;
    m.add_class::<TaskChannel>()?;
    Ok(())
}

/// 事件消息
#[derive(Clone)]
struct EventMessage {
    task_id: String,
    event_type: String,
    data: String,
}

impl EventMessage {
    fn to_json(&self) -> String {
        format!(
            r#"{{"task_id":"{}","event_type":"{}","data":{}}}"#,
            self.task_id, self.event_type, self.data
        )
    }
}

/// 单个任务的缓冲通道
#[pyclass]
pub struct TaskChannel {
    queue: std::sync::Arc<Mutex<VecDeque<String>>>,
}

#[pymethods]
impl TaskChannel {
    fn send(&self, msg: &str) -> bool {
        let mut q = self.queue.lock().unwrap();
        if q.len() >= MAX_CHANNEL_MESSAGES {
            q.pop_front();
        }
        q.push_back(msg.to_string());
        true
    }

    fn receive(&self, max_messages: usize) -> Vec<String> {
        let mut q = self.queue.lock().unwrap();
        let count = max_messages.min(q.len());
        q.drain(..count).collect()
    }

    fn pending_count(&self) -> usize {
        self.queue.lock().unwrap().len()
    }
}

/// Rust 事件总线
#[pyclass]
pub struct RustEventBus {
    channels: Mutex<HashMap<String, std::sync::Arc<Mutex<VecDeque<String>>>>>,
    event_count: Mutex<u64>,
    total_published: Mutex<u64>,
}

#[pymethods]
impl RustEventBus {
    #[new]
    fn new() -> Self {
        RustEventBus {
            channels: Mutex::new(HashMap::new()),
            event_count: Mutex::new(0),
            total_published: Mutex::new(0),
        }
    }

    /// 发布事件到指定任务通道
    fn publish(&self, task_id: &str, event_type: &str, data: &str) -> PyResult<bool> {
        let event = EventMessage {
            task_id: task_id.to_string(),
            event_type: event_type.to_string(),
            data: data.to_string(),
        };
        let json = event.to_json();

        let mut channels = self.channels.lock().unwrap();
        let queue = channels
            .entry(task_id.to_string())
            .or_insert_with(|| {
                *self.event_count.lock().unwrap() += 1;
                std::sync::Arc::new(Mutex::new(VecDeque::new()))
            })
            .clone();

        let mut q = queue.lock().unwrap();
        if q.len() >= MAX_CHANNEL_MESSAGES {
            q.pop_front();
        }
        q.push_back(json);
        *self.total_published.lock().unwrap() += 1;
        Ok(true)
    }

    /// 获取或创建任务通道
    fn get_channel(&self, task_id: &str) -> TaskChannel {
        let mut channels = self.channels.lock().unwrap();
        let queue = channels
            .entry(task_id.to_string())
            .or_insert_with(|| {
                *self.event_count.lock().unwrap() += 1;
                std::sync::Arc::new(Mutex::new(VecDeque::new()))
            })
            .clone();
        TaskChannel { queue }
    }

    /// 拉取任务通道中的消息
    fn receive_batch(&self, task_id: &str, max_messages: usize) -> Vec<String> {
        let channels = self.channels.lock().unwrap();
        if let Some(queue) = channels.get(task_id) {
            let mut q = queue.lock().unwrap();
            let count = max_messages.min(q.len());
            q.drain(..count).collect()
        } else {
            Vec::new()
        }
    }

    /// 移除任务通道
    fn remove_channel(&self, task_id: &str) -> bool {
        let mut channels = self.channels.lock().unwrap();
        channels.remove(task_id).is_some()
    }

    /// 获取统计信息
    fn get_stats(&self) -> PyResult<PyObject> {
        Python::with_gil(|py| {
            let channels = self.channels.lock().unwrap();
            let dict = pyo3::types::PyDict::new(py);
            dict.set_item("active_channels", channels.len())?;
            let total_pending: usize = channels.values().map(|q| q.lock().unwrap().len()).sum();
            dict.set_item("total_pending", total_pending)?;
            dict.set_item("total_created", *self.event_count.lock().unwrap())?;
            dict.set_item("total_published", *self.total_published.lock().unwrap())?;
            Ok(dict.into())
        })
    }

    fn health(&self) -> &'static str {
        "event_bus: operational (VecDeque buffer + mutex)"
    }
}
