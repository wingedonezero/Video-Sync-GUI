//! Sync executor component shell.
//!
//! Rust shell counterpart to `python/vsg_core/pipeline_components/sync_executor.py`.
//! Delegates merge execution to embedded Python.

use pyo3::prelude::*;

pub struct SyncExecutor;

impl SyncExecutor {
    pub fn execute_merge(
        py: Python<'_>,
        mkvmerge_options_path: &str,
        tool_paths: &PyAny,
        runner: &PyAny,
    ) -> PyResult<bool> {
        let module = py.import("vsg_core.pipeline_components.sync_executor")?;
        let class = module.getattr("SyncExecutor")?;
        class
            .call_method1("execute_merge", (mkvmerge_options_path, tool_paths, runner))?
            .extract::<bool>()
    }

    pub fn finalize_output(
        py: Python<'_>,
        temp_output_path: &PyAny,
        final_output_path: &PyAny,
        config: &PyAny,
        tool_paths: &PyAny,
        runner: &PyAny,
    ) -> PyResult<()> {
        let module = py.import("vsg_core.pipeline_components.sync_executor")?;
        let class = module.getattr("SyncExecutor")?;
        class.call_method1(
            "finalize_output",
            (temp_output_path, final_output_path, config, tool_paths, runner),
        )?;
        Ok(())
    }
}
