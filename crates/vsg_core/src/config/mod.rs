//! Configuration management for Video Sync GUI.
//!
//! This module provides:
//! - TOML-based configuration with logical sections
//! - Atomic file writes (write to temp, then rename)
//! - Section-level updates (only changed section is modified)
//! - Validation on load with automatic defaults
//!
//! # Example
//!
//! ```no_run
//! use vsg_core::config::{ConfigManager, ConfigSection};
//!
//! // Create manager and load (or create default) config
//! let mut config = ConfigManager::new(".config/settings.toml");
//! config.load_or_create().unwrap();
//!
//! // Read settings
//! println!("Output folder: {}", config.settings().paths.output_folder);
//!
//! // Modify a setting
//! config.settings_mut().logging.compact = false;
//!
//! // Save just the logging section atomically
//! config.update_section(ConfigSection::Logging).unwrap();
//! ```

mod manager;
mod settings;

pub use manager::{ConfigError, ConfigManager, ConfigResult};
pub use settings::{
    AnalysisSettings, ChapterSettings, ConfigSection, LoggingSettings, PathSettings,
    PostProcessSettings, Settings, SubtitleSettings,
};
