//! Application windows

pub mod main_window;
pub mod settings_window;

pub use main_window::MainWindow;
pub use settings_window::{SettingsInit, SettingsOutput, SettingsWindow};
