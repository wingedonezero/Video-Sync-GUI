// src/models/enums.rs
use pyo3::prelude::*;
use serde::{Deserialize, Serialize};

#[pyclass]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum TrackType {
    Video,
    Audio,
    Subtitles,
}

#[pymethods]
impl TrackType {
    fn __repr__(&self) -> String {
        format!("{:?}", self)
    }

    fn __str__(&self) -> String {
        match self {
            TrackType::Video => "video".to_string(),
            TrackType::Audio => "audio".to_string(),
            TrackType::Subtitles => "subtitles".to_string(),
        }
    }
}

#[pyclass]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum AnalysisMode {
    Audio,
    Video,
}

#[pymethods]
impl AnalysisMode {
    fn __repr__(&self) -> String {
        format!("{:?}", self)
    }

    fn __str__(&self) -> String {
        match self {
            AnalysisMode::Audio => "Audio Correlation".to_string(),
            AnalysisMode::Video => "VideoDiff".to_string(),
        }
    }
}

#[pyclass]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum SnapMode {
    Previous,
    Nearest,
}

#[pymethods]
impl SnapMode {
    fn __repr__(&self) -> String {
        format!("{:?}", self)
    }

    fn __str__(&self) -> String {
        match self {
            SnapMode::Previous => "previous".to_string(),
            SnapMode::Nearest => "nearest".to_string(),
        }
    }
}

#[pyclass]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum StepStatus {
    Pending,
    Running,
    Success,
    Skipped,
    Failed,
}

#[pymethods]
impl StepStatus {
    fn __repr__(&self) -> String {
        format!("{:?}", self)
    }
}

#[pyclass]
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum CorrectionVerdict {
    Uniform,
    Stepped,
    Failed,
}

#[pymethods]
impl CorrectionVerdict {
    fn __repr__(&self) -> String {
        format!("{:?}", self)
    }
}
