// src/lib.rs
use pyo3::prelude::*;
use pyo3::types::PyDict;
use numpy::PyReadonlyArray1;

mod models;
mod analysis;
mod correction;
mod subtitles;
mod extraction;
mod chapters;
mod mux;
mod orchestrator;
mod pipeline;
mod pipeline_components;
mod workers;
mod config;
mod ui_bridge;

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

    // Phase 6: Frame Utility functions
    m.add_function(wrap_pyfunction!(time_to_frame_floor, m)?)?;
    m.add_function(wrap_pyfunction!(frame_to_time_floor, m)?)?;
    m.add_function(wrap_pyfunction!(time_to_frame_middle, m)?)?;
    m.add_function(wrap_pyfunction!(frame_to_time_middle, m)?)?;
    m.add_function(wrap_pyfunction!(time_to_frame_aegisub, m)?)?;
    m.add_function(wrap_pyfunction!(frame_to_time_aegisub, m)?)?;

    // Phase 7: Extraction and Chapter functions
    m.add_function(wrap_pyfunction!(calculate_container_delay, m)?)?;
    m.add_function(wrap_pyfunction!(add_container_delays_to_json, m)?)?;
    m.add_function(wrap_pyfunction!(shift_chapter_timestamp, m)?)?;
    m.add_function(wrap_pyfunction!(format_chapter_timestamp, m)?)?;
    m.add_function(wrap_pyfunction!(parse_chapter_timestamp, m)?)?;

    // Phase 8: Mux Options functions
    m.add_function(wrap_pyfunction!(calculate_mux_delay, m)?)?;
    m.add_function(wrap_pyfunction!(build_mkvmerge_sync_token, m)?)?;

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

// ============================================================================
// Phase 6: Frame Utility Functions (PyO3 Bindings)
// ============================================================================

/// Convert timestamp to frame number using FLOOR with epsilon protection (MODE 0)
///
/// This gives the frame that is currently displaying at the given time.
/// Uses epsilon (1e-6) for floating point protection.
///
/// Args:
///     time_ms: Timestamp in milliseconds
///     fps: Frame rate (e.g., 23.976)
///
/// Returns:
///     Frame number (which frame is displaying at this time)
#[pyfunction]
fn time_to_frame_floor(time_ms: f64, fps: f64) -> i64 {
    subtitles::time_to_frame_floor(time_ms, fps)
}

/// Convert frame number to its START timestamp (MODE 0)
///
/// Frame N starts at exactly N * frame_duration. No rounding.
///
/// Args:
///     frame_num: Frame number
///     fps: Frame rate (e.g., 23.976)
///
/// Returns:
///     Timestamp in milliseconds (frame START time, as float for precision)
#[pyfunction]
fn frame_to_time_floor(frame_num: i64, fps: f64) -> f64 {
    subtitles::frame_to_time_floor(frame_num, fps)
}

/// Convert timestamp to frame number with +0.5 offset (MODE 1)
///
/// Targets middle of frame window.
///
/// Args:
///     time_ms: Timestamp in milliseconds
///     fps: Frame rate (e.g., 23.976)
///
/// Returns:
///     Frame number
#[pyfunction]
fn time_to_frame_middle(time_ms: f64, fps: f64) -> i64 {
    subtitles::time_to_frame_middle(time_ms, fps)
}

/// Convert frame number to middle of its display window (MODE 1)
///
/// Returns (frame_num + 0.5) * frame_duration, rounded to integer.
///
/// Args:
///     frame_num: Frame number
///     fps: Frame rate (e.g., 23.976)
///
/// Returns:
///     Timestamp in milliseconds (rounded to integer)
#[pyfunction]
fn frame_to_time_middle(frame_num: i64, fps: f64) -> i64 {
    subtitles::frame_to_time_middle(frame_num, fps)
}

/// Convert timestamp to frame number (MODE 2: Aegisub-style)
///
/// Uses floor division (which frame is currently displaying).
/// No epsilon adjustment.
///
/// Args:
///     time_ms: Timestamp in milliseconds
///     fps: Frame rate
///
/// Returns:
///     Frame number
#[pyfunction]
fn time_to_frame_aegisub(time_ms: f64, fps: f64) -> i64 {
    subtitles::time_to_frame_aegisub(time_ms, fps)
}

/// Convert frame number to Aegisub-style timestamp (MODE 2)
///
/// Calculates exact frame start, then rounds UP to next centisecond
/// to ensure timestamp falls within the frame.
///
/// Args:
///     frame_num: Frame number
///     fps: Frame rate
///
/// Returns:
///     Timestamp in milliseconds (rounded up to centisecond)
#[pyfunction]
fn frame_to_time_aegisub(frame_num: i64, fps: f64) -> i64 {
    subtitles::frame_to_time_aegisub(frame_num, fps)
}

// ============================================================================
// Phase 7: Extraction and Chapter Functions (PyO3 Bindings)
// ============================================================================

/// Calculate container delay in milliseconds from minimum_timestamp (nanoseconds)
///
/// CRITICAL: Uses round() not int() for proper handling of negative values.
///
/// Args:
///     minimum_timestamp_ns: Timestamp in nanoseconds from mkvmerge -J
///
/// Returns:
///     Container delay in milliseconds (rounded to nearest integer)
#[pyfunction]
fn calculate_container_delay(minimum_timestamp_ns: i64) -> i32 {
    extraction::calculate_container_delay(minimum_timestamp_ns)
}

/// Process mkvmerge -J JSON output to add container_delay_ms to tracks
///
/// Adds container_delay_ms field to each track based on minimum_timestamp.
/// ONLY audio and video tracks get calculated delays; subtitles always get 0.
///
/// Args:
///     json_str: JSON string from `mkvmerge -J <file>` command
///
/// Returns:
///     Modified JSON with container_delay_ms added to each track
///
/// Raises:
///     ValueError: If JSON is invalid
#[pyfunction]
fn add_container_delays_to_json(json_str: &str) -> PyResult<String> {
    extraction::add_container_delays_to_json(json_str)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

/// Shift a chapter timestamp by a given offset
///
/// Timestamps are in nanoseconds; shift is in milliseconds.
/// Negative results are clamped to 0.
///
/// Args:
///     timestamp_ns: Original timestamp in nanoseconds
///     shift_ms: Shift amount in milliseconds (can be negative)
///
/// Returns:
///     Shifted timestamp in nanoseconds (clamped to >= 0)
#[pyfunction]
fn shift_chapter_timestamp(timestamp_ns: i64, shift_ms: i64) -> i64 {
    chapters::shift_timestamp_ns(timestamp_ns, shift_ms)
}

/// Format nanoseconds as HH:MM:SS.nnnnnnnnn
///
/// Matches mkvmerge chapter timestamp format.
///
/// Args:
///     ns: Time in nanoseconds
///
/// Returns:
///     Formatted string: "HH:MM:SS.nnnnnnnnn"
#[pyfunction]
fn format_chapter_timestamp(ns: i64) -> String {
    chapters::format_ns(ns)
}

/// Parse timestamp string (HH:MM:SS.nnnnnnnnn) to nanoseconds
///
/// Args:
///     timestamp: Timestamp string in format "HH:MM:SS.nnnnnnnnn"
///
/// Returns:
///     Time in nanoseconds
///
/// Raises:
///     ValueError: If timestamp format is invalid
#[pyfunction]
fn parse_chapter_timestamp(timestamp: &str) -> PyResult<i64> {
    chapters::parse_ns(timestamp)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(e))
}

// ============================================================================
// Phase 8: Mux Options Functions (PyO3 Bindings)
// ============================================================================

/// Calculate the effective delay for a track to be used in mkvmerge
///
/// CRITICAL DELAY RULES:
/// - Source 1 VIDEO: Only global_shift (ignore container delays)
/// - Source 1 AUDIO: container_delay + global_shift
/// - Stepping-adjusted subtitles: Return 0 (delay baked in)
/// - Frame-adjusted subtitles: Return 0 (delay baked in)
/// - All other tracks: Use correlation delay from source_delays_ms
///
/// Args:
///     track_type: Type of track ("video", "audio", "subtitles")
///     source_key: Source identifier (e.g., "Source 1", "Source 2")
///     container_delay_ms: Container delay from track properties
///     global_shift_ms: Global shift to apply to all tracks
///     source_delays_ms: Dict mapping source keys to correlation delays
///     stepping_adjusted: Whether stepping correction was applied (default: False)
///     frame_adjusted: Whether frame-perfect sync was applied (default: False)
///
/// Returns:
///     Delay in milliseconds (signed integer)
#[pyfunction]
#[pyo3(signature = (track_type, source_key, container_delay_ms, global_shift_ms, source_delays_ms, stepping_adjusted=false, frame_adjusted=false))]
fn calculate_mux_delay(
    track_type: &str,
    source_key: &str,
    container_delay_ms: i32,
    global_shift_ms: i32,
    source_delays_ms: std::collections::HashMap<String, i32>,
    stepping_adjusted: bool,
    frame_adjusted: bool,
) -> PyResult<i32> {
    // Parse track type
    let track_type_enum = match track_type.to_lowercase().as_str() {
        "video" => mux::TrackType::Video,
        "audio" => mux::TrackType::Audio,
        "subtitles" => mux::TrackType::Subtitles,
        _ => return Err(pyo3::exceptions::PyValueError::new_err(
            format!("Invalid track_type: {}. Must be 'video', 'audio', or 'subtitles'", track_type)
        )),
    };

    let delay = mux::calculate_track_delay(
        track_type_enum,
        source_key,
        container_delay_ms,
        global_shift_ms,
        &source_delays_ms,
        stepping_adjusted,
        frame_adjusted,
    );

    Ok(delay)
}

/// Build mkvmerge sync token with signed delay format
///
/// CRITICAL: Delays must be signed format with explicit '+' or '-'
///
/// Args:
///     track_idx: Track index in mkvmerge (usually 0 for single-track inputs)
///     delay_ms: Delay in milliseconds (can be negative)
///
/// Returns:
///     List of tokens: ["--sync", "0:+500"]
#[pyfunction]
fn build_mkvmerge_sync_token(track_idx: u32, delay_ms: i32) -> Vec<String> {
    mux::build_sync_token(track_idx, delay_ms)
}
