//! Video Sync GUI - Main entry point
//!
//! This is the application entry point. It handles:
//! - Configuration loading
//! - Window creation
//! - Event loop execution
//!
//! Window-specific logic is in the `windows` module.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use slint::ComponentHandle;
use vsg_core::config::ConfigManager;

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
    // Load configuration
    let config_path = default_config_path();
    let mut config_manager = ConfigManager::new(&config_path);

    if let Err(e) = config_manager.load_or_create() {
        eprintln!("Warning: Failed to load config: {}. Using defaults.", e);
    }

    // Wrap config in Arc<Mutex> for sharing between callbacks
    let config = Arc::new(Mutex::new(config_manager));

    // Create the main window
    let main_window = MainWindow::new()?;

    // Log startup info
    let version_info = format!(
        "Video Sync GUI started.\nCore version: {}\nConfig: {}\n",
        vsg_core::version(),
        config_path.display()
    );
    main_window.set_log_text(version_info.into());

    // Set up all window callbacks and handlers
    setup_main_window(&main_window, Arc::clone(&config));

    // Run the event loop
    main_window.run()
}
