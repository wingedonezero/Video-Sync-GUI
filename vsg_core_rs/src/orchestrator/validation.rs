//! Orchestrator validation helpers.
//!
//! Rust shell counterpart to `python/vsg_core/orchestrator/validation.py`.
//! Validation rules remain in Python until they are ported in Phase 9+.

use pyo3::prelude::*;

pub struct StepValidator;

impl StepValidator {
    fn module(py: Python<'_>) -> PyResult<Bound<'_, PyModule>> {
        py.import("vsg_core.orchestrator.validation")
    }

    pub fn pipeline_validation_error(py: Python<'_>) -> PyResult<Py<PyAny>> {
        let module = Self::module(py)?;
        Ok(module.getattr("PipelineValidationError")?.into_py(py))
    }

    pub fn validate_analysis(py: Python<'_>, ctx: &PyAny) -> PyResult<()> {
        let module = Self::module(py)?;
        let validator = module.getattr("StepValidator")?;
        validator.call_method1("validate_analysis", (ctx,))?;
        Ok(())
    }

    pub fn validate_extraction(py: Python<'_>, ctx: &PyAny) -> PyResult<()> {
        let module = Self::module(py)?;
        let validator = module.getattr("StepValidator")?;
        validator.call_method1("validate_extraction", (ctx,))?;
        Ok(())
    }

    pub fn validate_correction(py: Python<'_>, ctx: &PyAny) -> PyResult<()> {
        let module = Self::module(py)?;
        let validator = module.getattr("StepValidator")?;
        validator.call_method1("validate_correction", (ctx,))?;
        Ok(())
    }

    pub fn validate_subtitles(py: Python<'_>, ctx: &PyAny) -> PyResult<()> {
        let module = Self::module(py)?;
        let validator = module.getattr("StepValidator")?;
        validator.call_method1("validate_subtitles", (ctx,))?;
        Ok(())
    }

    pub fn validate_mux(py: Python<'_>, ctx: &PyAny) -> PyResult<()> {
        let module = Self::module(py)?;
        let validator = module.getattr("StepValidator")?;
        validator.call_method1("validate_mux", (ctx,))?;
        Ok(())
    }
}
