//! Application windows

pub mod job_queue_window;
pub mod main_window;
pub mod settings_window;

pub use job_queue_window::{JobQueueInit, JobQueueOutput, JobQueueWindow};
pub use main_window::MainWindow;
pub use settings_window::{SettingsInit, SettingsOutput, SettingsWindow};
