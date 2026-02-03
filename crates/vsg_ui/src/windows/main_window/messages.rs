//! Main window messages (events)

use std::path::PathBuf;

use vsg_core::jobs::JobQueueEntry;
use vsg_core::models::Delays;

/// Messages for the main window
#[derive(Debug)]
pub enum MainWindowMsg {
    // === User actions from UI ===
    /// Settings button clicked
    OpenSettings,

    /// Settings dialog closed
    SettingsClosed,

    /// "Open Job Queue for Merging..." button clicked
    OpenJobQueue,

    /// Job queue dialog closed
    JobQueueClosed,

    /// Job queue requested to start processing (with configured job entries)
    StartProcessingQueue(Vec<JobQueueEntry>),

    /// Archive logs checkbox toggled
    ToggleArchiveLogs(bool),

    /// Source path changed (index 0-2, new path)
    SourcePathChanged { index: usize, path: String },

    /// Browse button clicked for source (index 0-2)
    BrowseSource(usize),

    /// File dialog returned a path
    BrowseResult { index: usize, path: Option<String> },

    /// "Analyze Only" button clicked
    RunAnalysis,

    // === Worker responses ===
    /// Analysis progress update
    AnalysisProgress { progress: f64, message: String },

    /// Log message from analysis
    AnalysisLog(String),

    /// Analysis completed
    AnalysisComplete(Result<AnalysisResult, String>),

    // === Queue processing responses ===
    /// Queue processing started for a job
    QueueJobStarted { job_id: String, job_name: String },

    /// Queue processing progress for a job
    QueueJobProgress {
        job_id: String,
        progress: f64,
        message: String,
    },

    /// Queue processing log message
    QueueLog(String),

    /// Single job completed
    QueueJobComplete {
        job_id: String,
        success: bool,
        output_path: Option<PathBuf>,
        error: Option<String>,
    },

    /// All queue processing finished
    QueueProcessingComplete {
        total: usize,
        succeeded: usize,
        failed: usize,
    },
}

/// Result from analysis worker
#[derive(Debug, Clone)]
pub struct AnalysisResult {
    pub delays: Delays,
}
