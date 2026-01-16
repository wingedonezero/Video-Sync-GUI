// src/lib.rs
use pyo3::prelude::*;
use pyo3::types::PyDict;
use numpy::PyReadonlyArray1;

mod models;
mod analysis;
mod correction;

#[pymodule]
fn vsg_core_rs(m: &Bound<'_, PyModule>) -> PyResult<()> {
    // Enums
    m.add_class::<models::enums::TrackType>()?;
    m.add_class::<models::enums::AnalysisMode>()?;
    m.add_class::<models::enums::SnapMode>()?;
    m.add_class::<models::enums::StepStatus>()?;
    m.add_class::<models::enums::CorrectionVerdict>()?;

    // Media
    m.add_class::<models::media::StreamProps>()?;
    m.add_class::<models::media::Track>()?;

    // Results
    m.add_class::<models::results::StepResult>()?;
    m.add_class::<models::results::CorrectionResult>()?;

    // Jobs
    m.add_class::<models::jobs::Delays>()?;
    m.add_class::<models::jobs::PlanItem>()?;

    // Settings
    m.add_class::<models::settings::AppSettings>()?;

    // Converter functions
    m.add_function(wrap_pyfunction!(models::converters::track_type_from_str, m)?)?;
    m.add_function(wrap_pyfunction!(models::converters::track_type_to_str, m)?)?;
    m.add_function(wrap_pyfunction!(models::converters::round_delay_ms, m)?)?;
    m.add_function(wrap_pyfunction!(models::converters::nanoseconds_to_ms, m)?)?;

    // Phase 2: Audio Correlation functions
    m.add_function(wrap_pyfunction!(analyze_audio_correlation, m)?)?;

    Ok(())
}

/// Analyze audio correlation between reference and target audio
///
/// Args:
///     ref_audio: Reference audio as float32 numpy array
///     tgt_audio: Target audio as float32 numpy array
///     sample_rate: Sample rate (default: 48000)
///     method: Correlation method ("gcc_phat", "scc", "gcc_scot", "gcc_whitened")
///     chunk_duration_s: Duration of each chunk in seconds (default: 15.0)
///     chunk_count: Number of chunks to analyze (default: 10)
///     min_match_pct: Minimum match percentage threshold (default: 5.0)
///     scan_start_pct: Start of scan range as percentage (default: 5.0)
///     scan_end_pct: End of scan range as percentage (default: 95.0)
///     delay_selection_mode: Mode for selecting final delay (default: "most_common")
///
/// Returns:
///     Dictionary with 'delay_ms' (int), 'raw_delay_ms' (float), and 'chunks' (list of dicts)
#[pyfunction]
#[pyo3(signature = (
    ref_audio,
    tgt_audio,
    sample_rate=48000,
    method="gcc_phat".to_string(),
    chunk_duration_s=15.0,
    chunk_count=10,
    min_match_pct=5.0,
    scan_start_pct=5.0,
    scan_end_pct=95.0,
    delay_selection_mode="most_common".to_string()
))]
fn analyze_audio_correlation(
    py: Python<'_>,
    ref_audio: PyReadonlyArray1<f32>,
    tgt_audio: PyReadonlyArray1<f32>,
    sample_rate: u32,
    method: String,
    chunk_duration_s: f64,
    chunk_count: usize,
    min_match_pct: f64,
    scan_start_pct: f64,
    scan_end_pct: f64,
    delay_selection_mode: String,
) -> PyResult<Py<PyDict>> {
    // Convert numpy arrays to slices
    let ref_slice = ref_audio.as_slice()?;
    let tgt_slice = tgt_audio.as_slice()?;

    // Parse correlation method
    let corr_method = match method.to_lowercase().as_str() {
        "gcc_phat" | "phase" => analysis::CorrelationMethod::GccPhat,
        "scc" | "standard" => analysis::CorrelationMethod::Scc,
        "gcc_scot" | "scot" => analysis::CorrelationMethod::GccScot,
        "gcc_whitened" | "whitened" => analysis::CorrelationMethod::GccWhitened,
        _ => analysis::CorrelationMethod::GccPhat,
    };

    // Parse delay selection mode
    let delay_mode = match delay_selection_mode.to_lowercase().as_str() {
        "most_common" | "mode" => analysis::DelaySelectionMode::MostCommon,
        "mode_clustered" | "clustered" => analysis::DelaySelectionMode::ModeClustered,
        "average" => analysis::DelaySelectionMode::Average,
        "first_stable" => analysis::DelaySelectionMode::FirstStable,
        _ => analysis::DelaySelectionMode::MostCommon,
    };

    // Build config
    let config = analysis::CorrelationConfig {
        chunk_duration_s,
        scan_start_pct,
        scan_end_pct,
        min_match_pct,
        chunk_count,
    };

    // Release GIL during computation
    let results = py.allow_threads(|| {
        analysis::run_correlation(
            ref_slice,
            tgt_slice,
            sample_rate,
            &config,
            corr_method,
        )
    });

    // Select final delay
    let delay_config = analysis::DelaySelectionConfig::default();
    let (delay_ms, raw_delay_ms) = analysis::select_final_delay(&results, delay_mode, &delay_config)
        .ok_or_else(|| pyo3::exceptions::PyValueError::new_err("Not enough accepted chunks"))?;

    // Build result dictionary
    let result = PyDict::new(py);
    result.set_item("delay_ms", delay_ms)?;
    result.set_item("raw_delay_ms", raw_delay_ms)?;

    // Convert chunks to Python list
    let chunks: Vec<_> = results.iter().map(|chunk| {
        let chunk_dict = PyDict::new(py);
        chunk_dict.set_item("delay", chunk.delay_ms).unwrap();
        chunk_dict.set_item("raw_delay", chunk.raw_delay_ms).unwrap();
        chunk_dict.set_item("match", chunk.confidence).unwrap();
        chunk_dict.set_item("start", chunk.start_time_s).unwrap();
        chunk_dict.set_item("accepted", chunk.accepted).unwrap();
        chunk_dict
    }).collect();

    result.set_item("chunks", chunks)?;

    Ok(result.into())
}
