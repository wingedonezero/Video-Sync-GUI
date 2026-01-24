//! Window modules for the Video Sync GUI.
//!
//! This module contains the Rust logic for each window, paralleling
//! the Slint layout files in `slint/windows/`.

mod main_window;
mod settings_window;

pub use main_window::setup_main_window;
