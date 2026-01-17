// src/models/jobs.rs
use pyo3::prelude::*;
use pyo3::types::PyDict;
use std::collections::HashMap;
use std::path::PathBuf;
use super::enums::TrackType;

#[pyclass]
#[derive(Clone, Debug, Default)]
pub struct Delays {
    /// Rounded delays for mkvmerge (integer milliseconds)
    #[pyo3(get, set)]
    pub source_delays_ms: HashMap<String, i32>,

    /// Raw delays for VideoTimestamps (float milliseconds)
    /// CRITICAL: Must have same keys as source_delays_ms
    #[pyo3(get, set)]
    pub raw_source_delays_ms: HashMap<String, f64>,

    #[pyo3(get, set)]
    pub global_shift_ms: i32,

    #[pyo3(get, set)]
    pub raw_global_shift_ms: f64,
}

#[pymethods]
impl Delays {
    #[new]
    #[pyo3(signature = (source_delays_ms=None, raw_source_delays_ms=None, global_shift_ms=0, raw_global_shift_ms=0.0))]
    fn new(
        source_delays_ms: Option<HashMap<String, i32>>,
        raw_source_delays_ms: Option<HashMap<String, f64>>,
        global_shift_ms: i32,
        raw_global_shift_ms: f64,
    ) -> Self {
        Delays {
            source_delays_ms: source_delays_ms.unwrap_or_default(),
            raw_source_delays_ms: raw_source_delays_ms.unwrap_or_default(),
            global_shift_ms,
            raw_global_shift_ms,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "Delays(source_delays_ms={:?}, raw_source_delays_ms={:?}, global_shift_ms={}, raw_global_shift_ms={})",
            self.source_delays_ms, self.raw_source_delays_ms, self.global_shift_ms, self.raw_global_shift_ms
        )
    }

    /// Convert to Python dictionary for JSON serialization
    fn to_dict(&self, py: Python) -> PyResult<Py<PyDict>> {
        let dict = PyDict::new(py);
        dict.set_item("source_delays_ms", self.source_delays_ms.clone())?;
        dict.set_item("raw_source_delays_ms", self.raw_source_delays_ms.clone())?;
        dict.set_item("global_shift_ms", self.global_shift_ms)?;
        dict.set_item("raw_global_shift_ms", self.raw_global_shift_ms)?;
        Ok(dict.into())
    }
}

#[pyclass]
#[derive(Clone, Debug)]
pub struct PlanItem {
    #[pyo3(get, set)]
    pub source_key: String,
    #[pyo3(get, set)]
    pub track_id: u32,
    #[pyo3(get, set)]
    pub track_type: TrackType,
    #[pyo3(get, set)]
    pub file_path: PathBuf,
    #[pyo3(get, set)]
    pub container_delay_ms: i32,

    // State flags - determine delay application
    #[pyo3(get, set)]
    pub is_preserved: bool,      // Original track kept
    #[pyo3(get, set)]
    pub is_corrected: bool,      // Underwent correction
    #[pyo3(get, set)]
    pub stepping_adjusted: bool, // Delay baked in (return 0)
    #[pyo3(get, set)]
    pub frame_adjusted: bool,    // Delay baked in (return 0)
    #[pyo3(get, set)]
    pub is_generated: bool,      // Created by style filtering
    #[pyo3(get, set)]
    pub generated_source_track_id: Option<u32>,
    #[pyo3(get, set)]
    pub generated_source_path: Option<PathBuf>,
}

#[pymethods]
impl PlanItem {
    #[new]
    #[pyo3(signature = (
        source_key,
        track_id,
        track_type,
        file_path,
        container_delay_ms,
        is_preserved=false,
        is_corrected=false,
        stepping_adjusted=false,
        frame_adjusted=false,
        is_generated=false,
        generated_source_track_id=None,
        generated_source_path=None
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        source_key: String,
        track_id: u32,
        track_type: TrackType,
        file_path: PathBuf,
        container_delay_ms: i32,
        is_preserved: bool,
        is_corrected: bool,
        stepping_adjusted: bool,
        frame_adjusted: bool,
        is_generated: bool,
        generated_source_track_id: Option<u32>,
        generated_source_path: Option<PathBuf>,
    ) -> Self {
        PlanItem {
            source_key,
            track_id,
            track_type,
            file_path,
            container_delay_ms,
            is_preserved,
            is_corrected,
            stepping_adjusted,
            frame_adjusted,
            is_generated,
            generated_source_track_id,
            generated_source_path,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "PlanItem(source_key='{}', track_id={}, track_type={:?}, file_path={:?}, container_delay_ms={})",
            self.source_key, self.track_id, self.track_type, self.file_path, self.container_delay_ms
        )
    }
}
