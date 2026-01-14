//! Configuration management
//!
//! Handles loading/saving settings, default values, and ensuring required
//! directories exist.

use crate::core::models::results::CoreResult;
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};

/// Application configuration
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AppConfig {
    // Storage & Tools
    pub output_folder: PathBuf,
    pub temp_root: PathBuf,
    pub videodiff_path: String,

    // Analysis
    pub analysis_mode: String,
    pub analysis_lang_ref: String,
    pub analysis_lang_sec: String,
    pub analysis_lang_ter: String,
    pub scan_chunk_count: u32,
    pub scan_chunk_duration: u32,
    pub min_match_pct: f64,
    pub videodiff_error_min: f64,
    pub videodiff_error_max: f64,

    // Workflow
    pub merge_mode: String,

    // Chapters
    pub rename_chapters: bool,
    pub snap_chapters: bool,
    pub snap_mode: String,
    pub snap_threshold_ms: u32,
    pub snap_starts_only: bool,

    // Merge Behavior
    pub apply_dialog_norm_gain: bool,
    pub exclude_codecs: String,
    pub disable_track_statistics_tags: bool,

    // Logging
    pub log_compact: bool,
    pub log_autoscroll: bool,
    pub log_progress_step: u32,
    pub log_error_tail: u32,
    pub log_tail_lines: u32,
    pub log_show_options_pretty: bool,
    pub log_show_options_json: bool,

    // Archival
    pub archive_logs: bool,

    // Auto-apply
    pub auto_apply_strict: bool,

    // Last paths (for UI convenience)
    pub last_ref_path: String,
    pub last_sec_path: String,
    pub last_ter_path: String,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            output_folder: PathBuf::from("sync_output"),
            temp_root: PathBuf::from("temp_work"),
            videodiff_path: String::new(),
            analysis_mode: "Audio Correlation".to_string(),
            analysis_lang_ref: String::new(),
            analysis_lang_sec: String::new(),
            analysis_lang_ter: String::new(),
            scan_chunk_count: 10,
            scan_chunk_duration: 15,
            min_match_pct: 5.0,
            videodiff_error_min: 0.0,
            videodiff_error_max: 100.0,
            merge_mode: "manual".to_string(),
            rename_chapters: false,
            snap_chapters: false,
            snap_mode: "previous".to_string(),
            snap_threshold_ms: 250,
            snap_starts_only: true,
            apply_dialog_norm_gain: false,
            exclude_codecs: String::new(),
            disable_track_statistics_tags: false,
            log_compact: true,
            log_autoscroll: true,
            log_progress_step: 20,
            log_error_tail: 20,
            log_tail_lines: 0,
            log_show_options_pretty: false,
            log_show_options_json: false,
            archive_logs: true,
            auto_apply_strict: false,
            last_ref_path: String::new(),
            last_sec_path: String::new(),
            last_ter_path: String::new(),
        }
    }
}

impl AppConfig {
    /// Load configuration from file
    pub fn load(path: &Path) -> CoreResult<Self> {
        if path.exists() {
            let contents = std::fs::read_to_string(path)?;
            let config: Self = serde_json::from_str(&contents)?;
            Ok(config)
        } else {
            // Return default if file doesn't exist
            Ok(Self::default())
        }
    }

    /// Save configuration to file
    pub fn save(&self, path: &Path) -> CoreResult<()> {
        let json = serde_json::to_string_pretty(self)?;
        std::fs::write(path, json)?;
        Ok(())
    }

    /// Ensure required directories exist
    pub fn ensure_directories(&self) -> CoreResult<()> {
        std::fs::create_dir_all(&self.output_folder)?;
        std::fs::create_dir_all(&self.temp_root)?;
        Ok(())
    }

    /// Get default settings file path (in current directory)
    pub fn default_path() -> PathBuf {
        PathBuf::from("settings.json")
    }

    /// Load from default location or create new
    pub fn load_or_default() -> CoreResult<Self> {
        let path = Self::default_path();
        let config = Self::load(&path)?;
        config.ensure_directories()?;
        Ok(config)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = AppConfig::default();
        assert_eq!(config.scan_chunk_count, 10);
        assert_eq!(config.scan_chunk_duration, 15);
        assert_eq!(config.min_match_pct, 5.0);
        assert!(config.log_compact);
    }

    #[test]
    fn test_config_serialization() {
        let config = AppConfig::default();
        let json = serde_json::to_string_pretty(&config).unwrap();
        let deserialized: AppConfig = serde_json::from_str(&json).unwrap();
        assert_eq!(config.scan_chunk_count, deserialized.scan_chunk_count);
    }
}
