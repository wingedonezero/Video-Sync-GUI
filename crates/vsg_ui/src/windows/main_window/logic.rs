//! Main window UI logic helpers

use super::model::MainWindowModel;

impl MainWindowModel {
    /// Check if we can run analysis (have required paths, not already running)
    pub fn can_run_analysis(&self) -> bool {
        !self.source1_path.is_empty() && !self.source2_path.is_empty() && !self.is_running
    }

    /// Format a delay value for display
    pub fn format_delay(delay_ms: Option<f64>) -> String {
        match delay_ms {
            Some(d) => format!("{:.0} ms", d),
            None => "—".to_string(),
        }
    }

    /// Append a log message (for sending to log view)
    pub fn format_log_line(&self, msg: &str) -> String {
        msg.to_string()
    }

    /// Get source path by index
    pub fn get_source_path(&self, index: usize) -> &str {
        match index {
            0 => &self.source1_path,
            1 => &self.source2_path,
            2 => &self.source3_path,
            _ => "",
        }
    }

    /// Set source path by index
    pub fn set_source_path(&mut self, index: usize, path: String) {
        match index {
            0 => self.source1_path = path,
            1 => self.source2_path = path,
            2 => self.source3_path = path,
            _ => {}
        }
    }

    /// Reset results before new analysis
    pub fn reset_results(&mut self) {
        self.source2_delay_ms = None;
        self.source3_delay_ms = None;
        self.source4_delay_ms = None;
    }

    /// Update progress display
    pub fn set_progress(&mut self, progress: f64, message: &str) {
        self.progress = progress.clamp(0.0, 1.0);
        self.status_message = message.to_string();
    }

    /// Mark analysis as started
    pub fn start_analysis(&mut self) {
        self.is_running = true;
        self.progress = 0.0;
        self.status_message = "Starting analysis...".to_string();
        self.reset_results();
    }

    /// Mark analysis as finished
    pub fn finish_analysis(&mut self, success: bool) {
        self.is_running = false;
        self.progress = if success { 1.0 } else { 0.0 };
        self.status_message = if success {
            "Analysis complete".to_string()
        } else {
            "Analysis failed".to_string()
        };
    }
}
