//! Log management component shell.
//!
//! Rust shell counterpart to `python/vsg_core/pipeline_components/log_manager.py`.
//! Delegates logger creation/cleanup to embedded Python.

use pyo3::prelude::*;

pub struct LogManager;

impl LogManager {
    pub fn setup_job_log(
        py: Python<'_>,
        job_name: &str,
        log_dir: &PyAny,
        gui_log_callback: &PyAny,
    ) -> PyResult<(PyObject, PyObject, PyObject)> {
        let module = py.import("vsg_core.pipeline_components.log_manager")?;
        let class = module.getattr("LogManager")?;
        let result = class.call_method1("setup_job_log", (job_name, log_dir, gui_log_callback))?;
        result.extract::<(PyObject, PyObject, PyObject)>()
    }

    pub fn cleanup_log(py: Python<'_>, logger: &PyAny, handler: &PyAny) -> PyResult<()> {
        let module = py.import("vsg_core.pipeline_components.log_manager")?;
        let class = module.getattr("LogManager")?;
        class.call_method1("cleanup_log", (logger, handler))?;
        Ok(())
    }
}
