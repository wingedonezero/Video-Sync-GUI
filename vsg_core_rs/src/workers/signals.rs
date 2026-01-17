//! Worker signal definitions (core).
//!
//! Rust-first signals that can optionally call into Python callbacks without
//! requiring Python UI modules.

use pyo3::prelude::*;

#[pyclass]
#[derive(Default)]
pub struct WorkerSignals {
    log_callback: Option<Py<PyAny>>,
    progress_callback: Option<Py<PyAny>>,
    status_callback: Option<Py<PyAny>>,
    finished_job_callback: Option<Py<PyAny>>,
    finished_all_callback: Option<Py<PyAny>>,
}

impl WorkerSignals {
    pub fn emit_log(&self, py: Python<'_>, message: &str) -> PyResult<()> {
        if let Some(cb) = &self.log_callback {
            cb.call1(py, (message,))?;
        }
        Ok(())
    }

    pub fn emit_progress(&self, py: Python<'_>, value: f32) -> PyResult<()> {
        if let Some(cb) = &self.progress_callback {
            cb.call1(py, (value,))?;
        }
        Ok(())
    }

    pub fn emit_status(&self, py: Python<'_>, message: &str) -> PyResult<()> {
        if let Some(cb) = &self.status_callback {
            cb.call1(py, (message,))?;
        }
        Ok(())
    }

    pub fn emit_finished_job(&self, py: Python<'_>, result: PyObject) -> PyResult<()> {
        if let Some(cb) = &self.finished_job_callback {
            cb.call1(py, (result,))?;
        }
        Ok(())
    }

    pub fn emit_finished_all(&self, py: Python<'_>, results: PyObject) -> PyResult<()> {
        if let Some(cb) = &self.finished_all_callback {
            cb.call1(py, (results,))?;
        }
        Ok(())
    }
}

#[pymethods]
impl WorkerSignals {
    #[new]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn set_log_callback(&mut self, callback: PyObject) {
        self.log_callback = Some(callback.into());
    }

    pub fn set_progress_callback(&mut self, callback: PyObject) {
        self.progress_callback = Some(callback.into());
    }

    pub fn set_status_callback(&mut self, callback: PyObject) {
        self.status_callback = Some(callback.into());
    }

    pub fn set_finished_job_callback(&mut self, callback: PyObject) {
        self.finished_job_callback = Some(callback.into());
    }

    pub fn set_finished_all_callback(&mut self, callback: PyObject) {
        self.finished_all_callback = Some(callback.into());
    }
}
