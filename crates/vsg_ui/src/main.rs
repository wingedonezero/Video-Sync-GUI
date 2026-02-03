//! Video Sync GUI - GTK4/Relm4 Application
//!
//! Main entry point. Initializes:
//! - Configuration
//! - Logging
//! - GTK application
//! - Main window

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use relm4::prelude::*;

use vsg_core::config::ConfigManager;

mod components;
mod windows;
mod workers;

use windows::MainWindow;

/// Default config path: .config/settings.toml
fn default_config_path() -> PathBuf {
    PathBuf::from(".config").join("settings.toml")
}

fn main() {
    // Load configuration
    let config_path = default_config_path();
    let mut config_manager = ConfigManager::new(&config_path);

    if let Err(e) = config_manager.load_or_create() {
        eprintln!("Warning: Failed to load config: {}. Using defaults.", e);
    }

    // Ensure directories exist
    if let Err(e) = config_manager.ensure_dirs_exist() {
        eprintln!("Warning: Failed to create directories: {}", e);
    }

    println!("Video Sync GUI starting...");
    println!("Config: {}", config_path.display());
    println!("Core version: {}", vsg_core::version());

    // Wrap config for sharing
    let config = Arc::new(Mutex::new(config_manager));

    // Create and run application
    let app = RelmApp::new("org.videosync.gui");
    app.run::<MainWindow>(config);
}
