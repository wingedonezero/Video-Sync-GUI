//! Worker signal definitions (shell).
//!
//! Mirrors `python/vsg_qt/worker/signals.py` for progress/logging events.
//! Uses embedded Python signals until UI wiring is ported.

use pyo3::exceptions::{PyAttributeError, PyRuntimeError};
use pyo3::prelude::*;
use pyo3::types::PyTuple;

#[derive(Clone)]
pub struct WorkerSignals {
    inner: Py<PyAny>,
}

impl WorkerSignals {
    pub fn new(py: Python<'_>) -> PyResult<Self> {
        let module = py.import("vsg_qt.worker.signals")?;
        let class = module.getattr("WorkerSignals")?;
        let instance = class.call0()?;
        Ok(Self {
            inner: instance.into_py(py),
        })
    }

    pub fn emit_log(&self, py: Python<'_>, message: &str) -> PyResult<()> {
        self.emit(py, "log", (message,))
    }

    pub fn emit_progress(&self, py: Python<'_>, value: f32) -> PyResult<()> {
        self.emit(py, "progress", (value,))
    }

    pub fn emit_status(&self, py: Python<'_>, message: &str) -> PyResult<()> {
        self.emit(py, "status", (message,))
    }

    pub fn emit_finished_job(&self, py: Python<'_>, result: &PyAny) -> PyResult<()> {
        self.emit(py, "finished_job", (result,))
    }

    pub fn emit_finished_all(&self, py: Python<'_>, results: &PyAny) -> PyResult<()> {
        self.emit(py, "finished_all", (results,))
    }

    fn emit<A>(&self, py: Python<'_>, name: &str, args: A) -> PyResult<()>
    where
        A: IntoPy<Py<PyTuple>>,
    {
        let signal = self.inner.as_ref(py).getattr(name)?;
        match signal.call_method1("emit", args) {
            Ok(_) => Ok(()),
            Err(err) => {
                if err.is_instance(py, PyRuntimeError::type_object(py))?
                    || err.is_instance(py, PyAttributeError::type_object(py))?
                {
                    Ok(())
                } else {
                    Err(err)
                }
            }
        }
    }

    pub fn as_py<'py>(&'py self, py: Python<'py>) -> &'py PyAny {
        self.inner.as_ref(py)
    }
}
