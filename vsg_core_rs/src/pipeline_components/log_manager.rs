//! Log management component core.
//!
//! Rust-first logging hooks that can forward to a GUI callback when provided.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

use pyo3::prelude::*;
use pyo3::types::PyAnyMethods;

#[pyclass]
struct LogToAll {
    log_path: PathBuf,
    callback: Option<Py<PyAny>>,
}

#[pymethods]
impl LogToAll {
    fn __call__(&self, py: Python<'_>, message: String) -> PyResult<()> {
        if let Ok(mut file) = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.log_path)
        {
            let _ = writeln!(file, "{}", message.trim());
        }
        if let Some(cb) = &self.callback {
            cb.call1(py, (message,))?;
        }
        Ok(())
    }
}

pub struct LogManager;

impl LogManager {
    pub fn setup_job_log(
        py: Python<'_>,
        job_name: &str,
        log_dir: &Path,
        gui_log_callback: PyObject,
    ) -> PyResult<(PyObject, PyObject, PyObject)> {
        std::fs::create_dir_all(log_dir)?;
        let log_path = log_dir.join(format!("{job_name}.log"));
        let callback_bound = gui_log_callback.bind(py);
        let callback = if callback_bound.is_none() {
            None
        } else {
            Some(gui_log_callback.into())
        };
        let log_to_all: Py<PyAny> = Py::new(
            py,
            LogToAll {
                log_path,
                callback,
            },
        )?
        .into();
        Ok((py.None(), py.None(), log_to_all.into()))
    }

    pub fn cleanup_log(_py: Python<'_>, _logger: PyObject, _handler: PyObject) -> PyResult<()> {
        Ok(())
    }
}
