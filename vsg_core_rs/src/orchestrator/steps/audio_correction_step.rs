//! Audio correction step shell.
//!
//! Rust shell counterpart to `python/vsg_core/orchestrator/steps/audio_correction_step.py`.
//! Delegates to embedded Python until the Rust implementation is ready.

use pyo3::prelude::*;

pub struct AudioCorrectionStep;

impl AudioCorrectionStep {
    pub fn run(py: Python<'_>, ctx: &PyAny, runner: &PyAny) -> PyResult<PyObject> {
        let module = py.import("vsg_core.orchestrator.steps.audio_correction_step")?;
        let step = module.getattr("AudioCorrectionStep")?.call0()?;
        let result = step.call_method1("run", (ctx, runner))?;
        Ok(result.into_py(py))
    }
}
