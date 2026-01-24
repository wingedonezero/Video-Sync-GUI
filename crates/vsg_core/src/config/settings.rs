//! Settings struct with TOML-based sections.
//!
//! Settings are organized into logical sections that map to TOML tables.
//! Each section can be updated independently for atomic section-level updates.

use serde::{Deserialize, Serialize};

use crate::models::{AnalysisMode, FilteringMethod, SnapMode};

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
}

impl Default for Settings {
    fn default() -> Self {
        Self {
            paths: PathSettings::default(),
            logging: LoggingSettings::default(),
            analysis: AnalysisSettings::default(),
            chapters: ChapterSettings::default(),
            postprocess: PostProcessSettings::default(),
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

impl Default for AnalysisSettings {
    fn default() -> Self {
        Self {
            mode: AnalysisMode::default(),
            lang_source1: None,
            lang_others: None,
            chunk_count: default_chunk_count(),
            chunk_duration: default_chunk_duration(),
            min_match_pct: default_min_match_pct(),
            scan_start_pct: default_scan_start(),
            scan_end_pct: default_scan_end(),
            use_soxr: true,
            audio_peak_fit: true,
            filtering_method: FilteringMethod::default(),
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

/// Names of config sections for targeted updates.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ConfigSection {
    Paths,
    Logging,
    Analysis,
    Chapters,
    Postprocess,
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
