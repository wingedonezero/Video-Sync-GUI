// src/models/settings.rs
use pyo3::prelude::*;
use super::enums::{AnalysisMode, SnapMode};

#[pyclass]
#[derive(Clone, Debug)]
pub struct AppSettings {
    #[pyo3(get, set)]
    pub output_folder: String,
    #[pyo3(get, set)]
    pub temp_root: String,
    #[pyo3(get, set)]
    pub videodiff_path: String,
    #[pyo3(get, set)]
    pub analysis_mode: AnalysisMode,
    #[pyo3(get, set)]
    pub analysis_lang_source1: Option<String>,
    #[pyo3(get, set)]
    pub analysis_lang_others: Option<String>,
    #[pyo3(get, set)]
    pub scan_chunk_count: i32,
    #[pyo3(get, set)]
    pub scan_chunk_duration: i32,
    #[pyo3(get, set)]
    pub min_match_pct: f64,
    #[pyo3(get, set)]
    pub videodiff_error_min: f64,
    #[pyo3(get, set)]
    pub videodiff_error_max: f64,
    #[pyo3(get, set)]
    pub rename_chapters: bool,
    #[pyo3(get, set)]
    pub snap_chapters: bool,
    #[pyo3(get, set)]
    pub snap_mode: SnapMode,
    #[pyo3(get, set)]
    pub snap_threshold_ms: i32,
    #[pyo3(get, set)]
    pub snap_starts_only: bool,
    #[pyo3(get, set)]
    pub apply_dialog_norm_gain: bool,
    #[pyo3(get, set)]
    pub disable_track_statistics_tags: bool,
    #[pyo3(get, set)]
    pub disable_header_compression: bool,
    #[pyo3(get, set)]
    pub log_compact: bool,
    #[pyo3(get, set)]
    pub log_autoscroll: bool,
    #[pyo3(get, set)]
    pub log_error_tail: i32,
    #[pyo3(get, set)]
    pub log_tail_lines: i32,
    #[pyo3(get, set)]
    pub log_progress_step: i32,
    #[pyo3(get, set)]
    pub log_show_options_pretty: bool,
    #[pyo3(get, set)]
    pub log_show_options_json: bool,
    #[pyo3(get, set)]
    pub archive_logs: bool,
    #[pyo3(get, set)]
    pub auto_apply_strict: bool,
    #[pyo3(get, set)]
    pub sync_mode: String,
}

#[pymethods]
impl AppSettings {
    #[new]
    #[pyo3(signature = (
        output_folder,
        temp_root,
        videodiff_path="".to_string(),
        analysis_mode=AnalysisMode::Audio,
        analysis_lang_source1=None,
        analysis_lang_others=None,
        scan_chunk_count=6,
        scan_chunk_duration=15,
        min_match_pct=5.0,
        videodiff_error_min=0.0,
        videodiff_error_max=100.0,
        rename_chapters=false,
        snap_chapters=false,
        snap_mode=SnapMode::Previous,
        snap_threshold_ms=100,
        snap_starts_only=false,
        apply_dialog_norm_gain=false,
        disable_track_statistics_tags=false,
        disable_header_compression=true,
        log_compact=false,
        log_autoscroll=true,
        log_error_tail=1,
        log_tail_lines=0,
        log_progress_step=5,
        log_show_options_pretty=false,
        log_show_options_json=false,
        archive_logs=false,
        auto_apply_strict=false,
        sync_mode="positive_only".to_string()
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        output_folder: String,
        temp_root: String,
        videodiff_path: String,
        analysis_mode: AnalysisMode,
        analysis_lang_source1: Option<String>,
        analysis_lang_others: Option<String>,
        scan_chunk_count: i32,
        scan_chunk_duration: i32,
        min_match_pct: f64,
        videodiff_error_min: f64,
        videodiff_error_max: f64,
        rename_chapters: bool,
        snap_chapters: bool,
        snap_mode: SnapMode,
        snap_threshold_ms: i32,
        snap_starts_only: bool,
        apply_dialog_norm_gain: bool,
        disable_track_statistics_tags: bool,
        disable_header_compression: bool,
        log_compact: bool,
        log_autoscroll: bool,
        log_error_tail: i32,
        log_tail_lines: i32,
        log_progress_step: i32,
        log_show_options_pretty: bool,
        log_show_options_json: bool,
        archive_logs: bool,
        auto_apply_strict: bool,
        sync_mode: String,
    ) -> Self {
        AppSettings {
            output_folder,
            temp_root,
            videodiff_path,
            analysis_mode,
            analysis_lang_source1,
            analysis_lang_others,
            scan_chunk_count,
            scan_chunk_duration,
            min_match_pct,
            videodiff_error_min,
            videodiff_error_max,
            rename_chapters,
            snap_chapters,
            snap_mode,
            snap_threshold_ms,
            snap_starts_only,
            apply_dialog_norm_gain,
            disable_track_statistics_tags,
            disable_header_compression,
            log_compact,
            log_autoscroll,
            log_error_tail,
            log_tail_lines,
            log_progress_step,
            log_show_options_pretty,
            log_show_options_json,
            archive_logs,
            auto_apply_strict,
            sync_mode,
        }
    }

    fn __repr__(&self) -> String {
        format!(
            "AppSettings(output_folder='{}', temp_root='{}', analysis_mode={:?}, sync_mode='{}')",
            self.output_folder, self.temp_root, self.analysis_mode, self.sync_mode
        )
    }
}
