//! Application windows

pub mod job_queue_window;
pub mod main_window;
pub mod manual_selection_window;
pub mod settings_window;

// Re-exports for public API (used via direct imports from sub-modules within crate)
#[allow(unused_imports)]
pub use job_queue_window::{JobQueueInit, JobQueueOutput, JobQueueWindow};
pub use main_window::MainWindow;
#[allow(unused_imports)]
pub use manual_selection_window::{
    ManualSelectionInit, ManualSelectionOutput, ManualSelectionWindow,
};
#[allow(unused_imports)]
pub use settings_window::{SettingsInit, SettingsOutput, SettingsWindow};
