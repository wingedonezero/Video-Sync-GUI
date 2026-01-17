//! Log management component core.
//!
//! Rust-first logging hooks that can forward to a GUI callback when provided.

use std::fs::OpenOptions;
use std::io::Write;
use std::path::{Path, PathBuf};

use pyo3::prelude::*;

#[pyclass]
struct LogToAll {
    log_path: PathBuf,
    callback: Option<Py<PyAny>>,
}

#[pymethods]
impl LogToAll {
    #[__call__]
    fn call(&self, py: Python<'_>, message: String) -> PyResult<()> {
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
        gui_log_callback: &PyAny,
    ) -> PyResult<(PyObject, PyObject, PyObject)> {
        std::fs::create_dir_all(log_dir)?;
        let log_path = log_dir.join(format!("{job_name}.log"));
        let callback = if gui_log_callback.is_none() {
            None
        } else {
            Some(gui_log_callback.to_object(py).into())
        };
        let log_to_all = Py::new(
            py,
            LogToAll {
                log_path,
                callback,
            },
        )?
        .into_py(py);
        Ok((py.None(), py.None(), log_to_all))
    }

    pub fn cleanup_log(_py: Python<'_>, _logger: &PyAny, _handler: &PyAny) -> PyResult<()> {
        Ok(())
    }
}
