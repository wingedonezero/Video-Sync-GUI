//! Application configuration management
//!
//! Bridges the Rust UI with the Python AppConfig via PyO3

use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// Configuration structure that mirrors vsg_core.config.AppConfig
/// This allows us to work with config in Rust while syncing with Python
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct AppConfig {
    // Storage paths
    pub output_folder: Option<PathBuf>,
    pub temp_root: Option<PathBuf>,
    pub videodiff_path: Option<PathBuf>,
    pub subtile_ocr_path: Option<PathBuf>,
    pub subtile_ocr_char_blacklist: Option<String>,

    // Analysis settings
    pub correlation_method: String,
    pub source_separation_model: String,
    pub filtering_method: String,
    pub audio_bandlimit_hz: u32,
    pub scan_chunk_count: u32,
    pub scan_chunk_duration: u32,
    pub min_match_pct: f64,
    pub min_accepted_chunks: u32,
    pub delay_selection_mode: String,
    pub first_stable_min_chunks: u32,
    pub first_stable_skip_unstable: bool,

    // Multi-correlation comparison
    pub multi_correlation_enabled: bool,
    pub multi_corr_scc: bool,
    pub multi_corr_gcc_phat: bool,
    pub multi_corr_onset: bool,
    pub multi_corr_gcc_scot: bool,
    pub multi_corr_dtw: bool,
    pub multi_corr_spectrogram: bool,

    // Subtitle cleanup
    pub ocr_cleanup_enabled: bool,
    pub ocr_cleanup_custom_wordlist_path: Option<PathBuf>,
    pub ocr_cleanup_normalize_ellipsis: bool,

    // Timing fixes
    pub timing_fix_enabled: bool,
    pub timing_fix_overlaps: bool,
    pub timing_overlap_min_gap_ms: u32,
    pub timing_fix_short_durations: bool,
    pub timing_min_duration_ms: u32,
    pub timing_fix_long_durations: bool,
    pub timing_max_cps: f64,

    // UI settings
    pub archive_logs_on_batch_completion: bool,
}

impl AppConfig {
    /// Load configuration from Python backend
    pub fn load() -> Self {
        // TODO: Call Python via PyO3 to load actual config
        // For now, return defaults
        Self::default()
    }

    /// Save configuration to Python backend
    pub fn save(&self) -> Result<(), String> {
        // TODO: Call Python via PyO3 to save config
        Ok(())
    }
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            output_folder: None,
            temp_root: None,
            videodiff_path: None,
            subtile_ocr_path: None,
            subtile_ocr_char_blacklist: None,

            correlation_method: "Standard Correlation (SCC)".to_string(),
            source_separation_model: "None (Use Original Audio)".to_string(),
            filtering_method: "Dialogue Band-Pass Filter".to_string(),
            audio_bandlimit_hz: 4000,
            scan_chunk_count: 10,
            scan_chunk_duration: 15,
            min_match_pct: 75.0,
            min_accepted_chunks: 3,
            delay_selection_mode: "Mode (Most Common)".to_string(),
            first_stable_min_chunks: 3,
            first_stable_skip_unstable: true,

            multi_correlation_enabled: false,
            multi_corr_scc: true,
            multi_corr_gcc_phat: true,
            multi_corr_onset: false,
            multi_corr_gcc_scot: false,
            multi_corr_dtw: false,
            multi_corr_spectrogram: false,

            ocr_cleanup_enabled: false,
            ocr_cleanup_custom_wordlist_path: None,
            ocr_cleanup_normalize_ellipsis: true,

            timing_fix_enabled: false,
            timing_fix_overlaps: true,
            timing_overlap_min_gap_ms: 50,
            timing_fix_short_durations: true,
            timing_min_duration_ms: 500,
            timing_fix_long_durations: false,
            timing_max_cps: 25.0,

            archive_logs_on_batch_completion: false,
        }
    }
}
