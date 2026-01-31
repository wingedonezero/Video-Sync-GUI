//! Video Sync GUI - Main entry point
//!
//! This is the application entry point using GTK4/Relm4. It handles:
//! - Application-level logging initialization
//! - Configuration loading
//! - Directory creation
//! - Application launch

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use relm4::prelude::*;
use relm4::RelmApp;

use vsg_core::config::ConfigManager;
use vsg_core::jobs::JobQueue;
use vsg_core::logging::{init_tracing_with_file, LogLevel};

mod app;
mod components;
mod theme;

use app::App;

/// Default config path: .config/settings.toml (relative to current working directory)
fn default_config_path() -> PathBuf {
    PathBuf::from(".config").join("settings.toml")
}

fn main() {
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

    // Create layout manager directory
    let layouts_dir = temp_folder.join("job_layouts");

    // Wrap config in Arc<Mutex> for sharing
    let config = Arc::new(Mutex::new(config_manager));

    // Create job queue with persistence
    let job_queue = Arc::new(Mutex::new(JobQueue::new(&temp_folder)));
    tracing::debug!("Job queue initialized at {}", temp_folder.display());

    tracing::info!("Application initialized, starting GTK4 event loop");

    // Build version info for initial log
    let version_info = format!(
        "Video Sync GUI started.\nCore version: {}\nConfig: {}\nLogs: {}\nLayouts: {}\n",
        vsg_core::version(),
        config_path.display(),
        logs_dir.display(),
        layouts_dir.display()
    );

    // Initialize Relm4 with libadwaita
    let app = RelmApp::new("io.github.videosyncgui");
    app.run::<App>(app::AppInit {
        config,
        job_queue,
        layouts_dir,
        version_info,
    });
}
