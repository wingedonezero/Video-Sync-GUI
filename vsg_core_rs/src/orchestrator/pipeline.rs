//! Orchestrator pipeline wiring.
//!
//! Rust-first placeholder that defines the orchestration entry point without
//! relying on embedded Python steps.

use pyo3::exceptions::PyRuntimeError;
use pyo3::prelude::*;

#[pyclass]
pub struct Orchestrator;

#[pymethods]
impl Orchestrator {
    #[new]
    pub fn new() -> Self {
        Self
    }

    #[allow(clippy::too_many_arguments)]
    #[pyo3(signature = (
        _settings_dict,
        _tool_paths,
        log,
        progress,
        _sources,
        _and_merge,
        _output_dir,
        _manual_layout=None,
        _attachment_sources=None
    ))]
    pub fn run(
        &self,
        py: Python<'_>,
        _settings_dict: PyObject,
        _tool_paths: PyObject,
        log: PyObject,
        progress: PyObject,
        _sources: PyObject,
        _and_merge: bool,
        _output_dir: String,
        _manual_layout: Option<PyObject>,
        _attachment_sources: Option<PyObject>,
    ) -> PyResult<PyObject> {
        log.as_ref(py).call1((
            "[ERROR] Rust orchestrator steps are not implemented yet.",
        ))?;
        progress.as_ref(py).call1((0.0f32,))?;
        Err(PyRuntimeError::new_err(
            "Rust orchestrator steps are not implemented yet.",
        ))
    }
}
