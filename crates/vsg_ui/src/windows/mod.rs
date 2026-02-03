//! Application windows

pub mod job_queue_window;
pub mod main_window;
pub mod manual_selection_window;
pub mod settings_window;

pub use job_queue_window::{JobQueueInit, JobQueueOutput, JobQueueWindow};
pub use main_window::MainWindow;
pub use manual_selection_window::{ManualSelectionInit, ManualSelectionOutput, ManualSelectionWindow};
pub use settings_window::{SettingsInit, SettingsOutput, SettingsWindow};
