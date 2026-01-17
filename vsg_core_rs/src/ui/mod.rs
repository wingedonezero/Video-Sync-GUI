//! libcosmic UI scaffolding for the Rust migration.
//!
//! This module mirrors the Python `vsg_qt` layout 1:1, providing window and
//! dialog structures that can be wired to the pipeline later.

pub mod common;
pub mod main_window;
pub mod job_queue_dialog;
pub mod add_job_dialog;
pub mod options_dialog;
pub mod manual_selection_dialog;
pub mod track_widget;
pub mod track_settings_dialog;
pub mod style_editor_dialog;
pub mod generated_track_dialog;
pub mod sync_exclusion_dialog;
pub mod resample_dialog;
pub mod model_manager_dialog;
