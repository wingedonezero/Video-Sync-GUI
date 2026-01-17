//! Orchestrator step context stub.
//!
//! Rust-first placeholder until the orchestrator context is fully ported.

use pyo3::prelude::*;

pub struct Context;

impl Context {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        _py: Python<'_>,
        _settings: &PyAny,
        _settings_dict: &PyAny,
        _tool_paths: &PyAny,
        _log: &PyAny,
        _progress: &PyAny,
        _output_dir: &str,
        _temp_dir: &PyAny,
        _sources: &PyAny,
        _and_merge: bool,
        _manual_layout: &PyAny,
        _attachment_sources: &PyAny,
    ) -> PyResult<Self> {
        Ok(Self)
    }

    pub fn from_py(_inner: Py<PyAny>) -> Self {
        Self
    }

    pub fn as_py(&self, py: Python<'_>) -> Py<PyAny> {
        py.None()
    }

    pub fn into_py(self, py: Python<'_>) -> PyObject {
        py.None()
    }
}
