//! Log management component core.
//!
//! Rust-first logging hooks that can forward to a GUI callback when provided.

use pyo3::prelude::*;

pub struct LogManager;

impl LogManager {
    pub fn setup_job_log(
        py: Python<'_>,
        _job_name: &str,
        _log_dir: &PyAny,
        gui_log_callback: &PyAny,
    ) -> PyResult<(PyObject, PyObject, PyObject)> {
        let logger = py.None();
        let handler = py.None();
        let log_to_all = gui_log_callback.to_object(py);
        Ok((logger, handler, log_to_all))
    }

    pub fn cleanup_log(_py: Python<'_>, _logger: &PyAny, _handler: &PyAny) -> PyResult<()> {
        Ok(())
    }
}
