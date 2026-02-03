//! Core types for the orchestrator pipeline.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::Arc;

use serde::{Deserialize, Serialize};

use crate::analysis::SourceStability;
use crate::config::Settings;
use crate::logging::JobLogger;
use crate::models::{Delays, JobSpec, MergePlan};

/// Progress callback type for reporting pipeline progress.
///
/// Arguments: (step_name, percent_complete, message)
pub type ProgressCallback = Box<dyn Fn(&str, u32, &str) + Send + Sync>;

/// Read-only context passed to pipeline steps.
///
/// Contains job configuration and shared resources that steps can read
/// but not modify. Mutable state goes in `JobState`.
pub struct Context {
    /// Job specification (sources, layout).
    pub job_spec: JobSpec,
    /// Application settings.
    pub settings: Settings,
    /// Job name/identifier.
    pub job_name: String,
    /// Job-specific working directory (under temp_root).
    pub work_dir: PathBuf,
    /// Output directory for final merged file.
    pub output_dir: PathBuf,
    /// Per-job logger.
    pub logger: Arc<JobLogger>,
    /// Optional progress callback.
    progress_callback: Option<ProgressCallback>,
}

impl Context {
    /// Create a new context for a job.
    pub fn new(
        job_spec: JobSpec,
        settings: Settings,
        job_name: impl Into<String>,
        work_dir: PathBuf,
        output_dir: PathBuf,
        logger: Arc<JobLogger>,
    ) -> Self {
        Self {
            job_spec,
            settings,
            job_name: job_name.into(),
            work_dir,
            output_dir,
            logger,
            progress_callback: None,
        }
    }

    /// Set the progress callback.
    pub fn with_progress_callback(mut self, callback: ProgressCallback) -> Self {
        self.progress_callback = Some(callback);
        self
    }

    /// Report progress to callback (if set).
    pub fn report_progress(&self, step_name: &str, percent: u32, message: &str) {
        if let Some(ref callback) = self.progress_callback {
            callback(step_name, percent, message);
        }
    }

    /// Get source file path by name.
    pub fn source_path(&self, name: &str) -> Option<&PathBuf> {
        self.job_spec.sources.get(name)
    }

    /// Get the primary source (Source 1) path.
    pub fn primary_source(&self) -> Option<&PathBuf> {
        self.source_path("Source 1")
    }
}

/// Mutable job state that accumulates results from pipeline steps.
///
/// This is the "write-once manifest" - steps can add new data but
/// should not overwrite existing values. Each step's output is stored
/// in its own section.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct JobState {
    /// Unique job identifier.
    pub job_id: String,
    /// When the job started.
    pub started_at: Option<String>,
    /// Analysis results (from Analyze step).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub analysis: Option<AnalysisOutput>,
    /// Extraction results (from Extract step).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub extract: Option<ExtractOutput>,
    /// Correction results (from audio correction steps).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub correction: Option<CorrectionOutput>,
    /// Subtitle processing results.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subtitles: Option<SubtitlesOutput>,
    /// Chapter processing results.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub chapters: Option<ChaptersOutput>,
    /// Mux step results.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mux: Option<MuxOutput>,
    /// The merge plan (built up during pipeline).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub merge_plan: Option<MergePlan>,
}

impl JobState {
    /// Create a new job state with the given ID.
    pub fn new(job_id: impl Into<String>) -> Self {
        Self {
            job_id: job_id.into(),
            started_at: Some(chrono::Local::now().to_rfc3339()),
            ..Default::default()
        }
    }

    /// Check if analysis has been completed.
    pub fn has_analysis(&self) -> bool {
        self.analysis.is_some()
    }

    /// Check if extraction has been completed.
    pub fn has_extraction(&self) -> bool {
        self.extract.is_some()
    }

    /// Get the calculated delays (if analysis completed).
    pub fn delays(&self) -> Option<&Delays> {
        self.analysis.as_ref().map(|a| &a.delays)
    }
}

/// Output from the Analysis step.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AnalysisOutput {
    /// Calculated sync delays.
    pub delays: Delays,
    /// Analysis confidence score (0.0 - 1.0).
    pub confidence: f64,
    /// Whether drift was detected in any source.
    pub drift_detected: bool,
    /// Analysis method used.
    pub method: String,
    /// Per-source stability metrics.
    #[serde(default)]
    pub source_stability: HashMap<String, SourceStability>,
}

// Note: SourceStability is imported from crate::analysis

/// Output from the Extraction step.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ExtractOutput {
    /// Extracted tracks and their paths.
    pub tracks: HashMap<String, PathBuf>,
    /// Extracted attachments and their paths.
    pub attachments: HashMap<String, PathBuf>,
}

/// Output from audio correction steps.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CorrectionOutput {
    /// Correction type applied (linear, pal, stepping).
    pub correction_type: String,
    /// Paths to corrected audio files.
    pub corrected_files: HashMap<String, PathBuf>,
}

/// Output from subtitle processing.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SubtitlesOutput {
    /// Processed subtitle files.
    pub processed_files: HashMap<String, PathBuf>,
    /// OCR was performed.
    pub ocr_performed: bool,
}

/// Output from chapter processing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChaptersOutput {
    /// Path to chapters XML file.
    pub chapters_xml: Option<PathBuf>,
    /// Whether chapters were snapped to keyframes.
    pub snapped: bool,
}

/// Output from the Mux step.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MuxOutput {
    /// Path to final merged file.
    pub output_path: PathBuf,
    /// mkvmerge exit code.
    pub exit_code: i32,
    /// mkvmerge command that was run.
    pub command: String,
}

/// Result of executing a pipeline step.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum StepOutcome {
    /// Step completed successfully.
    Success,
    /// Step was skipped (preconditions not met, but not an error).
    Skipped(String),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn job_state_tracks_completion() {
        let mut state = JobState::new("test-123");
        assert!(!state.has_analysis());

        state.analysis = Some(AnalysisOutput {
            delays: Delays::default(),
            confidence: 0.95,
            drift_detected: false,
            method: "audio_correlation".to_string(),
            source_stability: HashMap::new(),
        });

        assert!(state.has_analysis());
    }

    #[test]
    fn job_state_serializes() {
        let state = JobState::new("test-456");
        let json = serde_json::to_string(&state).unwrap();
        assert!(json.contains("\"job_id\":\"test-456\""));
    }
}
