//! Sync planner component shell.
//!
//! Rust shell counterpart to `python/vsg_core/pipeline_components/sync_planner.py`.
//! Delegates planning to the Rust orchestrator, which embeds Python steps.

use pyo3::prelude::*;

use crate::orchestrator::pipeline::Orchestrator;

pub struct SyncPlanner;

impl SyncPlanner {
    #[allow(clippy::too_many_arguments)]
    pub fn plan_sync(
        py: Python<'_>,
        config: &PyAny,
        tool_paths: &PyAny,
        log_callback: &PyAny,
        progress_callback: &PyAny,
        sources: &PyAny,
        and_merge: bool,
        output_dir: &str,
        manual_layout: &PyAny,
        attachment_sources: &PyAny,
    ) -> PyResult<PyObject> {
        let orchestrator = Orchestrator::new();
        orchestrator.run(
            py,
            config.into_py(py),
            tool_paths.into_py(py),
            log_callback.into_py(py),
            progress_callback.into_py(py),
            sources.into_py(py),
            and_merge,
            output_dir.to_string(),
            Some(manual_layout.into_py(py)),
            Some(attachment_sources.into_py(py)),
        )
    }
}
