// src/models/converters.rs
use pyo3::prelude::*;
use super::enums::TrackType;

/// Convert a string to TrackType enum
#[pyfunction]
pub fn track_type_from_str(s: &str) -> PyResult<TrackType> {
    match s.to_lowercase().as_str() {
        "video" => Ok(TrackType::Video),
        "audio" => Ok(TrackType::Audio),
        "subtitles" | "subtitle" => Ok(TrackType::Subtitles),
        _ => Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(
            format!("Invalid track type: {}", s)
        )),
    }
}

/// Convert TrackType enum to string
#[pyfunction]
pub fn track_type_to_str(track_type: TrackType) -> String {
    match track_type {
        TrackType::Video => "video".to_string(),
        TrackType::Audio => "audio".to_string(),
        TrackType::Subtitles => "subtitles".to_string(),
    }
}

/// Round a float millisecond value to integer, preserving sign
#[pyfunction]
pub fn round_delay_ms(delay_ms: f64) -> i32 {
    delay_ms.round() as i32
}

/// Convert nanoseconds to milliseconds with proper rounding
/// CRITICAL: Used for container_delay_ms calculation from mkvmerge JSON
#[pyfunction]
pub fn nanoseconds_to_ms(ns: i64) -> i32 {
    (ns as f64 / 1_000_000.0).round() as i32
}
