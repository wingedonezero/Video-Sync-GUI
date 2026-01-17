//! Subtitle processing step shell.
//!
//! Rust shell counterpart to `python/vsg_core/orchestrator/steps/subtitles_step.py`.
//! Delegates to embedded Python until the Rust implementation is ready.

use pyo3::prelude::*;

pub struct SubtitlesStep;

impl SubtitlesStep {
    pub fn run(py: Python<'_>, _ctx: &PyAny, _runner: &PyAny) -> PyResult<PyObject> {
        Ok(py.None())
    }
}
