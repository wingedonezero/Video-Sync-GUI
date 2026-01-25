//! Analysis pipeline handlers.

use std::collections::HashMap;
use std::path::PathBuf;

use iced::Task;

use vsg_core::models::JobSpec;

use crate::app::{App, Message};
use super::helpers::run_analyze_only;

impl App {
    /// Start the analysis pipeline.
    pub fn start_analysis(&mut self) -> Task<Message> {
        if self.source1_path.is_empty() || self.source2_path.is_empty() {
            self.append_log("[WARNING] Please select at least Source 1 and Source 2");
            return Task::none();
        }

        self.is_analyzing = true;
        self.status_text = "Analyzing...".to_string();
        self.progress_value = 0.0;

        self.append_log("=== Starting Analysis ===");
        self.append_log(&format!("Source 1: {}", self.source1_path));
        self.append_log(&format!("Source 2: {}", self.source2_path));
        if !self.source3_path.is_empty() {
            self.append_log(&format!("Source 3: {}", self.source3_path));
        }

        // Build job spec
        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), PathBuf::from(&self.source1_path));
        sources.insert("Source 2".to_string(), PathBuf::from(&self.source2_path));
        if !self.source3_path.is_empty() {
            sources.insert("Source 3".to_string(), PathBuf::from(&self.source3_path));
        }

        let job_spec = JobSpec::new(sources);
        let settings = {
            let cfg = self.config.lock().unwrap();
            cfg.settings().clone()
        };

        // Run analysis in background
        Task::perform(
            async move { run_analyze_only(job_spec, settings).await },
            |result| match result {
                Ok((delay2, delay3)) => Message::AnalysisComplete {
                    delay_source2_ms: delay2,
                    delay_source3_ms: delay3,
                },
                Err(e) => Message::AnalysisFailed(e),
            },
        )
    }

    /// Handle analysis complete.
    pub fn handle_analysis_complete(
        &mut self,
        delay_source2_ms: Option<i64>,
        delay_source3_ms: Option<i64>,
    ) {
        self.is_analyzing = false;
        self.progress_value = 100.0;
        self.status_text = "Ready".to_string();

        if let Some(delay) = delay_source2_ms {
            self.delay_source2 = format!("{} ms", delay);
            self.append_log(&format!("Source 2 delay: {} ms", delay));
        }
        if let Some(delay) = delay_source3_ms {
            self.delay_source3 = format!("{} ms", delay);
            self.append_log(&format!("Source 3 delay: {} ms", delay));
        }

        self.append_log("=== Analysis Complete ===");
    }

    /// Handle analysis failed.
    pub fn handle_analysis_failed(&mut self, error: &str) {
        self.is_analyzing = false;
        self.progress_value = 0.0;
        self.status_text = "Analysis Failed".to_string();
        self.append_log(&format!("[ERROR] {}", error));
    }
}
