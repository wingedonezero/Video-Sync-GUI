//! Sync planner component core.
//!
//! Rust-first placeholder that prepares a minimal planning context without
//! invoking Python modules.

use std::path::PathBuf;

use pyo3::prelude::*;

#[derive(Debug)]
pub struct SyncPlanContext {
    pub temp_dir: PathBuf,
    pub tokens: Option<Vec<String>>,
    pub delays: Vec<(String, i64)>,
    pub stepping_sources: Vec<String>,
    pub stepping_detected_disabled: bool,
}

pub struct SyncPlanner;

impl SyncPlanner {
    #[allow(clippy::too_many_arguments)]
    pub fn plan_sync(
        _py: Python<'_>,
        _config: &PyAny,
        _tool_paths: &PyAny,
        _log_callback: &PyAny,
        _progress_callback: &PyAny,
        _sources: &PyAny,
        _and_merge: bool,
        output_dir: &str,
        _manual_layout: &PyAny,
        _attachment_sources: &PyAny,
    ) -> PyResult<SyncPlanContext> {
        let temp_dir = PathBuf::from(output_dir).join("temp_work");
        std::fs::create_dir_all(&temp_dir)?;
        Ok(SyncPlanContext {
            temp_dir,
            tokens: None,
            delays: Vec::new(),
            stepping_sources: Vec::new(),
            stepping_detected_disabled: false,
        })
    }
}
