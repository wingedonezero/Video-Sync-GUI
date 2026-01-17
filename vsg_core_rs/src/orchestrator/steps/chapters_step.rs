//! Chapters step shell.
//!
//! Rust shell counterpart to `python/vsg_core/orchestrator/steps/chapters_step.py`.
//! Delegates to embedded Python until the Rust implementation is ready.

use pyo3::prelude::*;

pub struct ChaptersStep;

impl ChaptersStep {
    pub fn run(py: Python<'_>, _ctx: &PyAny, _runner: &PyAny) -> PyResult<PyObject> {
        Ok(py.None())
    }
}
