//! Mux planning step shell.
//!
//! Rust shell counterpart to `python/vsg_core/orchestrator/steps/mux_step.py`.
//! Delegates to embedded Python until the Rust implementation is ready.

use pyo3::prelude::*;

pub struct MuxStep;

impl MuxStep {
    pub fn run(py: Python<'_>, ctx: &PyAny, runner: &PyAny) -> PyResult<PyObject> {
        let module = py.import("vsg_core.orchestrator.steps.mux_step")?;
        let step = module.getattr("MuxStep")?.call0()?;
        let result = step.call_method1("run", (ctx, runner))?;
        Ok(result.into_py(py))
    }
}
