//! Job queue window messages

use std::collections::HashMap;
use std::path::PathBuf;

use vsg_core::jobs::JobQueueEntry;

/// Messages for the job queue window
#[derive(Debug)]
pub enum JobQueueMsg {
    // === Job management ===
    /// Open dialog to add new jobs
    AddJobs,
    /// Jobs discovered from AddJobDialog
    JobsDiscovered(Vec<DiscoveredJob>),
    /// Remove selected jobs from queue
    RemoveSelected,
    /// Move selected jobs up in the queue
    MoveUp,
    /// Move selected jobs down in the queue
    MoveDown,
    /// Clear all jobs from the queue
    ClearAll,

    // === Layout operations ===
    /// Copy layout from selected job
    CopyLayout,
    /// Paste layout to selected jobs
    PasteLayout,
    /// Open manual selection dialog for selected job
    ConfigureSelected,

    // === Selection ===
    /// Job selection changed
    SelectionChanged(Vec<u32>),
    /// Double-click to configure job
    JobDoubleClicked(u32),

    // === Dialog actions ===
    /// Start processing the queue
    StartProcessing,
    /// Cancel and close dialog
    Cancel,

    // === Browse dialog results ===
    /// Browse result for source files
    BrowseResult {
        source_index: usize,
        paths: Vec<PathBuf>,
    },

    // === Manual selection dialog ===
    /// Manual selection dialog closed with layout configured
    LayoutConfigured {
        job_index: usize,
        layout: Vec<crate::windows::manual_selection_window::FinalTrackData>,
        attachment_sources: Vec<String>,
    },
    /// Manual selection dialog cancelled
    LayoutConfigurationCancelled,
}

/// A discovered job entry (from add job dialog)
#[derive(Debug, Clone)]
pub struct DiscoveredJob {
    /// Unique job ID
    pub id: String,
    /// Display name
    pub name: String,
    /// Map of source keys to file paths
    pub sources: HashMap<String, PathBuf>,
}

/// Output message sent to parent when dialog closes
#[derive(Debug)]
pub enum JobQueueOutput {
    /// User clicked Start Processing (returns configured job entries)
    StartProcessing(Vec<JobQueueEntry>),
    /// Dialog was cancelled
    Cancelled,
}
