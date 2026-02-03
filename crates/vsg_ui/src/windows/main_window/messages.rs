//! Main window messages (events)

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

    /// Job queue requested to start processing
    StartProcessingQueue(Vec<String>),

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
}

/// Result from analysis worker
#[derive(Debug, Clone)]
pub struct AnalysisResult {
    pub delays: Delays,
}
