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
        _config: &Bound<'_, PyAny>,
        _tool_paths: &Bound<'_, PyAny>,
        _log_callback: &Bound<'_, PyAny>,
        _progress_callback: &Bound<'_, PyAny>,
        _sources: &Bound<'_, PyAny>,
        _and_merge: bool,
        output_dir: &str,
        _manual_layout: &Bound<'_, PyAny>,
        _attachment_sources: &Bound<'_, PyAny>,
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
