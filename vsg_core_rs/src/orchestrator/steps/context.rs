//! Orchestrator step context shell.
//!
//! Rust shell counterpart to `python/vsg_core/orchestrator/steps/context.py`.
//! The Rust layer owns lifecycle wiring while the underlying context remains a
//! Python dataclass until fully ported.

use pyo3::prelude::*;

#[derive(Clone)]
pub struct Context {
    inner: Py<PyAny>,
}

impl Context {
    pub fn new(
        py: Python<'_>,
        settings: &PyAny,
        settings_dict: &PyAny,
        tool_paths: &PyAny,
        log: &PyAny,
        progress: &PyAny,
        output_dir: &str,
        temp_dir: &PyAny,
        sources: &PyAny,
        and_merge: bool,
        manual_layout: &PyAny,
        attachment_sources: &PyAny,
    ) -> PyResult<Self> {
        let module = py.import("vsg_core.orchestrator.steps.context")?;
        let class = module.getattr("Context")?;
        let instance = class.call1((
            settings,
            settings_dict,
            tool_paths,
            log,
            progress,
            output_dir,
            temp_dir,
            sources,
            and_merge,
            manual_layout,
            attachment_sources,
        ))?;
        Ok(Self {
            inner: instance.into_py(py),
        })
    }

    pub fn from_py(inner: Py<PyAny>) -> Self {
        Self { inner }
    }

    pub fn as_py<'py>(&'py self, py: Python<'py>) -> &'py PyAny {
        self.inner.as_ref(py)
    }

    pub fn into_py(self, py: Python<'_>) -> PyObject {
        self.inner.into_py(py)
    }
}
