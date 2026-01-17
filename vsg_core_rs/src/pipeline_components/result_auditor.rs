//! Result auditor component shell.
//!
//! Rust shell counterpart to `python/vsg_core/pipeline_components/result_auditor.py`.
//! Delegates auditing to embedded Python.

use pyo3::prelude::*;

pub struct ResultAuditor;

impl ResultAuditor {
    pub fn audit_output(
        py: Python<'_>,
        output_file: &PyAny,
        context: &PyAny,
        runner: &PyAny,
        log_callback: &PyAny,
    ) -> PyResult<i32> {
        let module = py.import("vsg_core.pipeline_components.result_auditor")?;
        let class = module.getattr("ResultAuditor")?;
        class
            .call_method1("audit_output", (output_file, context, runner, log_callback))?
            .extract::<i32>()
    }
}
