//! Window modules for the Video Sync GUI.
//!
//! This module contains the Rust logic for each window, paralleling
//! the Slint layout files in `slint/windows/`.

mod main_window;
mod settings_window;
pub mod add_job_dialog;
pub mod job_queue_dialog;
pub mod manual_selection_dialog;
pub mod track_settings_dialog;

pub use main_window::setup_main_window;
