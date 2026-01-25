//! Video Sync GUI - Main entry point
//!
//! This is the application entry point using iced. It handles:
//! - Application-level logging initialization
//! - Configuration loading
//! - Directory creation
//! - Application launch

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use vsg_core::config::ConfigManager;
use vsg_core::jobs::JobQueue;
use vsg_core::logging::{init_tracing_with_file, LogLevel};

mod app;
mod handlers;
mod pages;
mod theme;
mod windows;

use app::App;

/// Default config path: .config/settings.toml (relative to current working directory)
fn default_config_path() -> PathBuf {
    PathBuf::from(".config").join("settings.toml")
}

fn main() -> iced::Result {
    // Load configuration first (needed for logs directory path)
    let config_path = default_config_path();
    let mut config_manager = ConfigManager::new(&config_path);

    if let Err(e) = config_manager.load_or_create() {
        eprintln!("Warning: Failed to load config: {}. Using defaults.", e);
    }

    // Initialize application-level logging
    let logs_dir = config_manager.logs_folder();
    let _log_guard = init_tracing_with_file(LogLevel::Info, &logs_dir);

    tracing::info!("Video Sync GUI starting");
    tracing::info!("Config: {}", config_path.display());
    tracing::info!("Core version: {}", vsg_core::version());

    // Ensure all configured directories exist
    if let Err(e) = config_manager.ensure_dirs_exist() {
        tracing::error!("Failed to create directories: {}", e);
        eprintln!("Warning: Failed to create directories: {}", e);
    }

    // Get temp folder path for job queue persistence
    let temp_folder = PathBuf::from(&config_manager.settings().paths.temp_root);

    // Wrap config in Arc<Mutex> for sharing
    let config = Arc::new(Mutex::new(config_manager));

    // Create job queue with persistence
    let job_queue = Arc::new(Mutex::new(JobQueue::new(&temp_folder)));
    tracing::debug!("Job queue initialized at {}", temp_folder.display());

    tracing::info!("Application initialized, starting event loop");

    // Run the application
    App::run(config, job_queue, config_path, logs_dir)
}
