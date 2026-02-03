//! Main window state model

/// Main window state
#[derive(Debug, Default)]
pub struct MainWindowModel {
    // Source paths
    pub source1_path: String,
    pub source2_path: String,
    pub source3_path: String,

    // Analysis results (displayed after analysis completes)
    pub source2_delay_ms: Option<f64>,
    pub source3_delay_ms: Option<f64>,
    pub source4_delay_ms: Option<f64>,

    // Status and progress
    pub status_message: String,
    pub progress: f64, // 0.0 - 1.0
    pub is_running: bool,

    // Settings
    pub archive_logs_on_completion: bool,
}

impl MainWindowModel {
    pub fn new() -> Self {
        Self {
            status_message: "Ready".to_string(),
            ..Default::default()
        }
    }
}
