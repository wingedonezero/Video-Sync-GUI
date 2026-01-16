// src/models/results.rs
use pyo3::prelude::*;
use super::enums::StepStatus;

#[pyclass]
#[derive(Clone, Debug)]
pub struct StepResult {
    #[pyo3(get, set)]
    pub status: StepStatus,
    #[pyo3(get, set)]
    pub error: Option<String>,
    #[pyo3(get, set)]
    pub warnings: Vec<String>,
}

#[pymethods]
impl StepResult {
    #[new]
    #[pyo3(signature = (status, error=None, warnings=None))]
    fn new(status: StepStatus, error: Option<String>, warnings: Option<Vec<String>>) -> Self {
        StepResult {
            status,
            error,
            warnings: warnings.unwrap_or_default(),
        }
    }

    fn is_fatal(&self) -> bool {
        matches!(self.status, StepStatus::Failed)
    }

    fn has_issues(&self) -> bool {
        !matches!(self.status, StepStatus::Success) || !self.warnings.is_empty()
    }

    fn add_warning(&mut self, message: String) {
        self.warnings.push(message);
        if matches!(self.status, StepStatus::Success) {
            self.status = StepStatus::Pending;  // Adjust status if needed
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "StepResult(status={:?}, error={:?}, warnings={:?})",
            self.status, self.error, self.warnings
        )
    }
}

#[pyclass]
#[derive(Clone, Debug)]
pub struct CorrectionResult {
    #[pyo3(get, set)]
    pub success: bool,
    #[pyo3(get, set)]
    pub error: Option<String>,
    #[pyo3(get, set)]
    pub corrected_tracks: Vec<String>,
}

#[pymethods]
impl CorrectionResult {
    #[new]
    #[pyo3(signature = (success, error=None, corrected_tracks=None))]
    fn new(success: bool, error: Option<String>, corrected_tracks: Option<Vec<String>>) -> Self {
        CorrectionResult {
            success,
            error,
            corrected_tracks: corrected_tracks.unwrap_or_default(),
        }
    }

    #[staticmethod]
    fn failed(error: String) -> Self {
        CorrectionResult {
            success: false,
            error: Some(error),
            corrected_tracks: Vec::new(),
        }
    }

    #[staticmethod]
    fn succeeded(corrected_tracks: Vec<String>) -> Self {
        CorrectionResult {
            success: true,
            error: None,
            corrected_tracks,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "CorrectionResult(success={}, error={:?}, corrected_tracks={:?})",
            self.success, self.error, self.corrected_tracks
        )
    }
}
