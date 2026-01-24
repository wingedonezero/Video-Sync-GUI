//! Video Sync GUI - Main entry point
//!
//! This is the application entry point. It handles:
//! - Application-level logging initialization
//! - Configuration loading
//! - Directory creation
//! - Window creation
//! - Event loop execution
//!
//! Window-specific logic is in the `windows` module.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use slint::ComponentHandle;
use vsg_core::config::ConfigManager;
use vsg_core::logging::{init_tracing_with_file, LogLevel};

mod ui;
mod windows;

use ui::MainWindow;
use windows::setup_main_window;

/// Default config path: ~/.config/video-sync-gui/settings.toml
fn default_config_path() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("video-sync-gui")
        .join("settings.toml")
}

fn main() -> Result<(), slint::PlatformError> {
    // Load configuration first (needed for logs directory path)
    let config_path = default_config_path();
    let mut config_manager = ConfigManager::new(&config_path);

    if let Err(e) = config_manager.load_or_create() {
        eprintln!("Warning: Failed to load config: {}. Using defaults.", e);
    }

    // Initialize application-level logging
    // This writes to both stderr and {logs_folder}/app.log
    // The guard must be kept alive for the duration of the program
    let logs_dir = config_manager.logs_folder();
    let _log_guard = init_tracing_with_file(LogLevel::Info, &logs_dir);

    tracing::info!("Video Sync GUI starting");
    tracing::info!("Config: {}", config_path.display());
    tracing::info!("Core version: {}", vsg_core::version());

    // Ensure all configured directories exist (output, temp, logs)
    if let Err(e) = config_manager.ensure_dirs_exist() {
        tracing::error!("Failed to create directories: {}", e);
        eprintln!("Warning: Failed to create directories: {}", e);
    }

    // Wrap config in Arc<Mutex> for sharing between callbacks
    let config = Arc::new(Mutex::new(config_manager));

    // Create the main window
    let main_window = MainWindow::new()?;
    tracing::debug!("Main window created");

    // Log startup info to the GUI log panel
    let version_info = format!(
        "Video Sync GUI started.\nCore version: {}\nConfig: {}\nLogs: {}\n",
        vsg_core::version(),
        config_path.display(),
        logs_dir.display()
    );
    main_window.set_log_text(version_info.into());

    // Set up all window callbacks and handlers
    setup_main_window(&main_window, Arc::clone(&config));

    tracing::info!("Application initialized, starting event loop");

    // Run the event loop
    let result = main_window.run();

    tracing::info!("Application shutting down");

    result
}
