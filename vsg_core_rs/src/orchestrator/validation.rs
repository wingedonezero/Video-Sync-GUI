//! Orchestrator validation helpers.
//!
//! Rust-first placeholder until validation rules are ported.

use pyo3::prelude::*;

pub struct StepValidator;

impl StepValidator {
    pub fn pipeline_validation_error(py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(py.None())
    }

    pub fn validate_analysis(_py: Python<'_>, _ctx: &PyAny) -> PyResult<()> {
        Ok(())
    }

    pub fn validate_extraction(_py: Python<'_>, _ctx: &PyAny) -> PyResult<()> {
        Ok(())
    }

    pub fn validate_correction(_py: Python<'_>, _ctx: &PyAny) -> PyResult<()> {
        Ok(())
    }

    pub fn validate_subtitles(_py: Python<'_>, _ctx: &PyAny) -> PyResult<()> {
        Ok(())
    }

    pub fn validate_mux(_py: Python<'_>, _ctx: &PyAny) -> PyResult<()> {
        Ok(())
    }
}
