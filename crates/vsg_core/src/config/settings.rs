//! Settings struct with TOML-based sections.
//!
//! Settings are organized into logical sections that map to TOML tables.
//! Each section can be updated independently for atomic section-level updates.

use serde::{Deserialize, Serialize};

use crate::analysis::OutlierMode;
use crate::models::{
    AnalysisMode, CorrelationMethod, DelaySelectionMode, FilteringMethod, SnapMode, SyncMode,
};
use crate::subtitles::frame_utils::{
    ComparisonMethod, DeinterlaceMethod, HashAlgorithm, IndexerBackend,
};
use crate::subtitles::sync::SyncModeType;

/// Root settings structure containing all configuration sections.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Settings {
    /// Path-related settings.
    #[serde(default)]
    pub paths: PathSettings,

    /// Logging configuration.
    #[serde(default)]
    pub logging: LoggingSettings,

    /// Analysis settings.
    #[serde(default)]
    pub analysis: AnalysisSettings,

    /// Chapter handling settings.
    #[serde(default)]
    pub chapters: ChapterSettings,

    /// Post-processing settings.
    #[serde(default)]
    pub postprocess: PostProcessSettings,

    /// Subtitle sync settings.
    #[serde(default)]
    pub subtitle: SubtitleSettings,
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            paths: PathSettings::default(),
            logging: LoggingSettings::default(),
            analysis: AnalysisSettings::default(),
            chapters: ChapterSettings::default(),
            postprocess: PostProcessSettings::default(),
            subtitle: SubtitleSettings::default(),
        }
    }
}

/// Path configuration for output, temp, and logs.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PathSettings {
    /// Output folder for merged files.
    #[serde(default = "default_output_folder")]
    pub output_folder: String,

    /// Root folder for temporary files.
    #[serde(default = "default_temp_root")]
    pub temp_root: String,

    /// Folder for log files.
    #[serde(default = "default_logs_folder")]
    pub logs_folder: String,

    /// Last used path for source 1.
    #[serde(default)]
    pub last_source1_path: String,

    /// Last used path for source 2.
    #[serde(default)]
    pub last_source2_path: String,
}

fn default_output_folder() -> String {
    "sync_output".to_string()
}

fn default_temp_root() -> String {
    ".temp".to_string()
}

fn default_logs_folder() -> String {
    ".logs".to_string()
}

impl Default for PathSettings {
    fn default() -> Self {
        Self {
            output_folder: default_output_folder(),
            temp_root: default_temp_root(),
            logs_folder: default_logs_folder(),
            last_source1_path: String::new(),
            last_source2_path: String::new(),
        }
    }
}

/// Logging configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LoggingSettings {
    /// Use compact log format.
    #[serde(default = "default_true")]
    pub compact: bool,

    /// Auto-scroll log output.
    #[serde(default = "default_true")]
    pub autoscroll: bool,

    /// Number of error lines to show in tail.
    #[serde(default = "default_error_tail")]
    pub error_tail: u32,

    /// Progress update step percentage.
    #[serde(default = "default_progress_step")]
    pub progress_step: u32,

    /// Show mkvmerge options in pretty format.
    #[serde(default)]
    pub show_options_pretty: bool,

    /// Show mkvmerge options as raw JSON.
    #[serde(default)]
    pub show_options_json: bool,

    /// Archive logs after job completion.
    #[serde(default = "default_true")]
    pub archive_logs: bool,
}

fn default_true() -> bool {
    true
}

fn default_error_tail() -> u32 {
    20
}

fn default_progress_step() -> u32 {
    20
}

impl Default for LoggingSettings {
    fn default() -> Self {
        Self {
            compact: true,
            autoscroll: true,
            error_tail: default_error_tail(),
            progress_step: default_progress_step(),
            show_options_pretty: false,
            show_options_json: false,
            archive_logs: true,
        }
    }
}

/// Analysis configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalysisSettings {
    /// Analysis mode (audio correlation or video diff).
    #[serde(default)]
    pub mode: AnalysisMode,

    /// Correlation algorithm to use.
    #[serde(default)]
    pub correlation_method: CorrelationMethod,

    /// Language filter for source 1 audio.
    #[serde(default)]
    pub lang_source1: Option<String>,

    /// Language filter for other sources.
    #[serde(default)]
    pub lang_others: Option<String>,

    /// Number of chunks to scan.
    #[serde(default = "default_chunk_count")]
    pub chunk_count: u32,

    /// Duration of each chunk in seconds.
    #[serde(default = "default_chunk_duration")]
    pub chunk_duration: u32,

    /// Minimum match percentage required.
    #[serde(default = "default_min_match_pct")]
    pub min_match_pct: f64,

    /// Minimum number of accepted chunks required for valid analysis.
    #[serde(default = "default_min_accepted_chunks")]
    pub min_accepted_chunks: u32,

    /// Scan start position as percentage.
    #[serde(default = "default_scan_start")]
    pub scan_start_pct: f64,

    /// Scan end position as percentage.
    #[serde(default = "default_scan_end")]
    pub scan_end_pct: f64,

    /// Use SOXR high-quality resampling via FFmpeg.
    #[serde(default = "default_true")]
    pub use_soxr: bool,

    /// Use quadratic peak fitting for sub-sample accuracy.
    #[serde(default = "default_true")]
    pub audio_peak_fit: bool,

    /// Audio filtering method before correlation.
    #[serde(default)]
    pub filtering_method: FilteringMethod,

    /// Low cutoff frequency for filtering (Hz).
    #[serde(default = "default_filter_low_cutoff")]
    pub filter_low_cutoff_hz: f64,

    /// High cutoff frequency for filtering (Hz).
    #[serde(default = "default_filter_high_cutoff")]
    pub filter_high_cutoff_hz: f64,

    /// Enable multi-correlation comparison mode (Analyze Only).
    /// Runs all correlation methods on the same data for comparison.
    #[serde(default)]
    pub multi_correlation_enabled: bool,

    /// [Multi-Correlation] Enable SCC method.
    #[serde(default = "default_true")]
    pub multi_corr_scc: bool,

    /// [Multi-Correlation] Enable GCC-PHAT method.
    #[serde(default = "default_true")]
    pub multi_corr_gcc_phat: bool,

    /// [Multi-Correlation] Enable GCC-SCOT method.
    #[serde(default = "default_true")]
    pub multi_corr_gcc_scot: bool,

    /// [Multi-Correlation] Enable Whitened method.
    #[serde(default = "default_true")]
    pub multi_corr_whitened: bool,

    /// [Multi-Correlation] Enable Onset Detection method.
    #[serde(default = "default_true")]
    pub multi_corr_onset: bool,

    /// [Multi-Correlation] Enable DTW (Dynamic Time Warping) method.
    #[serde(default = "default_true")]
    pub multi_corr_dtw: bool,

    /// [Multi-Correlation] Enable Spectrogram Correlation method.
    #[serde(default = "default_true")]
    pub multi_corr_spectrogram: bool,

    /// Method for selecting final delay from chunk measurements.
    #[serde(default)]
    pub delay_selection_mode: DelaySelectionMode,

    /// [First Stable] Minimum consecutive chunks with same delay for stability.
    #[serde(default = "default_first_stable_min_chunks")]
    pub first_stable_min_chunks: u32,

    /// [First Stable] Skip segments below min chunk threshold.
    #[serde(default)]
    pub first_stable_skip_unstable: bool,

    /// [Early Cluster] Number of early chunks to check for stability.
    #[serde(default = "default_early_cluster_window")]
    pub early_cluster_window: u32,

    /// [Early Cluster] Minimum chunks in early window for stability.
    #[serde(default = "default_early_cluster_threshold")]
    pub early_cluster_threshold: u32,

    /// Sync mode controls how negative delays are handled.
    /// PositiveOnly applies global shift to eliminate negatives.
    /// AllowNegative keeps delays as-is (may not work with some players).
    #[serde(default)]
    pub sync_mode: SyncMode,

    // === Sync Stability Settings ===
    /// Enable sync stability analysis (check for variance in chunk delays).
    #[serde(default)]
    pub sync_stability_enabled: bool,

    /// Variance threshold in ms for stability warning.
    /// Set to 0 for strict mode (any variance triggers warning).
    #[serde(default = "default_variance_threshold")]
    pub sync_stability_variance_threshold: f64,

    /// Minimum number of accepted chunks required for stability analysis.
    #[serde(default = "default_stability_min_chunks")]
    pub sync_stability_min_chunks: u32,

    /// Mode for detecting outliers in delay measurements.
    #[serde(default)]
    pub sync_stability_outlier_mode: OutlierMode,

    /// Threshold in ms for outlier detection (Threshold mode only).
    #[serde(default = "default_outlier_threshold")]
    pub sync_stability_outlier_threshold: f64,
}

fn default_chunk_count() -> u32 {
    10
}

fn default_chunk_duration() -> u32 {
    15
}

fn default_min_match_pct() -> f64 {
    5.0
}

fn default_scan_start() -> f64 {
    5.0
}

fn default_scan_end() -> f64 {
    95.0
}

fn default_min_accepted_chunks() -> u32 {
    3
}

fn default_first_stable_min_chunks() -> u32 {
    3
}

fn default_early_cluster_window() -> u32 {
    10
}

fn default_early_cluster_threshold() -> u32 {
    5
}

fn default_filter_low_cutoff() -> f64 {
    300.0 // Dialogue low cutoff
}

fn default_filter_high_cutoff() -> f64 {
    3400.0 // Dialogue high cutoff
}

fn default_variance_threshold() -> f64 {
    5.0 // 5ms variance threshold
}

fn default_stability_min_chunks() -> u32 {
    3 // Minimum chunks for stability analysis
}

fn default_outlier_threshold() -> f64 {
    5.0 // 5ms outlier threshold
}

impl Default for AnalysisSettings {
    fn default() -> Self {
        Self {
            mode: AnalysisMode::default(),
            correlation_method: CorrelationMethod::default(),
            lang_source1: None,
            lang_others: None,
            chunk_count: default_chunk_count(),
            chunk_duration: default_chunk_duration(),
            min_match_pct: default_min_match_pct(),
            min_accepted_chunks: default_min_accepted_chunks(),
            scan_start_pct: default_scan_start(),
            scan_end_pct: default_scan_end(),
            use_soxr: true,
            audio_peak_fit: true,
            filtering_method: FilteringMethod::default(),
            filter_low_cutoff_hz: default_filter_low_cutoff(),
            filter_high_cutoff_hz: default_filter_high_cutoff(),
            multi_correlation_enabled: false,
            multi_corr_scc: true,
            multi_corr_gcc_phat: true,
            multi_corr_gcc_scot: true,
            multi_corr_whitened: true,
            multi_corr_onset: true,
            multi_corr_dtw: true,
            multi_corr_spectrogram: true,
            delay_selection_mode: DelaySelectionMode::default(),
            first_stable_min_chunks: default_first_stable_min_chunks(),
            first_stable_skip_unstable: false,
            early_cluster_window: default_early_cluster_window(),
            early_cluster_threshold: default_early_cluster_threshold(),
            sync_mode: SyncMode::default(),
            sync_stability_enabled: false,
            sync_stability_variance_threshold: default_variance_threshold(),
            sync_stability_min_chunks: default_stability_min_chunks(),
            sync_stability_outlier_mode: OutlierMode::default(),
            sync_stability_outlier_threshold: default_outlier_threshold(),
        }
    }
}

/// Chapter handling configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChapterSettings {
    /// Rename chapters.
    #[serde(default)]
    pub rename: bool,

    /// Snap chapters to keyframes.
    #[serde(default)]
    pub snap_enabled: bool,

    /// Snap mode (previous or nearest).
    #[serde(default)]
    pub snap_mode: SnapMode,

    /// Snap threshold in milliseconds.
    #[serde(default = "default_snap_threshold")]
    pub snap_threshold_ms: u32,

    /// Only snap chapter starts (not ends).
    #[serde(default = "default_true")]
    pub snap_starts_only: bool,
}

fn default_snap_threshold() -> u32 {
    250
}

impl Default for ChapterSettings {
    fn default() -> Self {
        Self {
            rename: false,
            snap_enabled: false,
            snap_mode: SnapMode::default(),
            snap_threshold_ms: default_snap_threshold(),
            snap_starts_only: true,
        }
    }
}

/// Post-processing configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PostProcessSettings {
    /// Disable track statistics tags.
    #[serde(default)]
    pub disable_track_stats_tags: bool,

    /// Disable header compression.
    #[serde(default = "default_true")]
    pub disable_header_compression: bool,

    /// Apply dialog normalization gain.
    #[serde(default)]
    pub apply_dialog_norm: bool,
}

impl Default for PostProcessSettings {
    fn default() -> Self {
        Self {
            disable_track_stats_tags: false,
            disable_header_compression: true,
            apply_dialog_norm: false,
        }
    }
}

/// Subtitle sync configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SubtitleSettings {
    /// Sync mode for subtitles (time-based or video-verified).
    #[serde(default)]
    pub sync_mode: SyncModeType,

    // === Video-Verified General Settings ===
    /// Number of checkpoints to verify across the video.
    #[serde(default = "default_num_checkpoints")]
    pub num_checkpoints: u32,

    /// Search range in frames around expected position.
    #[serde(default = "default_search_range_frames")]
    pub search_range_frames: i32,

    /// Number of consecutive frames required to confirm a match.
    #[serde(default = "default_sequence_length")]
    pub sequence_length: u32,

    /// Enable frame audit logging.
    #[serde(default)]
    pub frame_audit_enabled: bool,

    // === Hash Settings ===
    /// Hash algorithm for frame comparison.
    #[serde(default)]
    pub hash_algorithm: HashAlgorithm,

    /// Hash size (8, 16, or 32).
    #[serde(default = "default_hash_size")]
    pub hash_size: u32,

    /// Threshold for hash distance (lower = stricter).
    #[serde(default = "default_hash_threshold")]
    pub hash_threshold: u32,

    /// Comparison method (hash or SSIM/MSE).
    #[serde(default)]
    pub comparison_method: ComparisonMethod,

    /// SSIM threshold (0.0-1.0, higher = stricter).
    #[serde(default = "default_ssim_threshold")]
    pub ssim_threshold: f64,

    // === Indexer Settings ===
    /// VapourSynth indexer backend.
    #[serde(default)]
    pub indexer_backend: IndexerBackend,

    // === Interlaced Handling ===
    /// Enable special handling for interlaced content.
    #[serde(default)]
    pub interlaced_handling_enabled: bool,

    /// Deinterlace method for interlaced content.
    #[serde(default)]
    pub deinterlace_method: DeinterlaceMethod,

    /// Hash threshold for interlaced content (usually higher).
    #[serde(default = "default_interlaced_hash_threshold")]
    pub interlaced_hash_threshold: u32,

    /// SSIM threshold for interlaced content (usually lower).
    #[serde(default = "default_interlaced_ssim_threshold")]
    pub interlaced_ssim_threshold: f64,
}

fn default_num_checkpoints() -> u32 {
    5
}

fn default_search_range_frames() -> i32 {
    3
}

fn default_sequence_length() -> u32 {
    10
}

fn default_hash_size() -> u32 {
    16
}

fn default_hash_threshold() -> u32 {
    12
}

fn default_ssim_threshold() -> f64 {
    0.85
}

fn default_interlaced_hash_threshold() -> u32 {
    18
}

fn default_interlaced_ssim_threshold() -> f64 {
    0.70
}

impl Default for SubtitleSettings {
    fn default() -> Self {
        Self {
            sync_mode: SyncModeType::default(),
            num_checkpoints: default_num_checkpoints(),
            search_range_frames: default_search_range_frames(),
            sequence_length: default_sequence_length(),
            frame_audit_enabled: false,
            hash_algorithm: HashAlgorithm::default(),
            hash_size: default_hash_size(),
            hash_threshold: default_hash_threshold(),
            comparison_method: ComparisonMethod::default(),
            ssim_threshold: default_ssim_threshold(),
            indexer_backend: IndexerBackend::default(),
            interlaced_handling_enabled: false,
            deinterlace_method: DeinterlaceMethod::default(),
            interlaced_hash_threshold: default_interlaced_hash_threshold(),
            interlaced_ssim_threshold: default_interlaced_ssim_threshold(),
        }
    }
}

/// Names of config sections for targeted updates.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ConfigSection {
    Paths,
    Logging,
    Analysis,
    Chapters,
    Postprocess,
    Subtitle,
}

impl ConfigSection {
    /// Get the TOML table name for this section.
    pub fn table_name(&self) -> &'static str {
        match self {
            ConfigSection::Paths => "paths",
            ConfigSection::Logging => "logging",
            ConfigSection::Analysis => "analysis",
            ConfigSection::Chapters => "chapters",
            ConfigSection::Postprocess => "postprocess",
            ConfigSection::Subtitle => "subtitle",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_settings_serializes() {
        let settings = Settings::default();
        let toml = toml::to_string_pretty(&settings).unwrap();
        assert!(toml.contains("[paths]"));
        assert!(toml.contains("[logging]"));
        assert!(toml.contains("output_folder"));
    }

    #[test]
    fn settings_round_trip() {
        let settings = Settings::default();
        let toml = toml::to_string_pretty(&settings).unwrap();
        let parsed: Settings = toml::from_str(&toml).unwrap();
        assert_eq!(parsed.paths.output_folder, settings.paths.output_folder);
        assert_eq!(parsed.logging.compact, settings.logging.compact);
    }

    #[test]
    fn missing_fields_use_defaults() {
        let minimal = "[paths]\noutput_folder = \"custom_output\"";
        let parsed: Settings = toml::from_str(minimal).unwrap();
        // Custom value preserved
        assert_eq!(parsed.paths.output_folder, "custom_output");
        // Defaults applied for missing
        assert_eq!(parsed.logging.compact, true);
        assert_eq!(parsed.analysis.chunk_count, 10);
    }
}
