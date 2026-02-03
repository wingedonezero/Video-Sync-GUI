//! Queue processor for running jobs from the job queue.
//!
//! This module provides the `QueueProcessor` which takes jobs from
//! the queue and runs them through the standard pipeline.

use std::path::PathBuf;
use std::sync::Arc;

use crate::config::Settings;
use crate::jobs::{JobQueueEntry, JobQueueStatus};
use crate::logging::{GuiLogCallback, JobLogger, LogConfig};
use crate::models::JobSpec;

use super::pipeline::CancelHandle;
use super::types::{Context, JobState, ProgressCallback};
use super::{create_standard_pipeline, PipelineRunResult};

/// Result of processing a single job.
#[derive(Debug, Clone)]
pub struct JobResult {
    /// Job ID that was processed.
    pub job_id: String,
    /// Whether the job completed successfully.
    pub success: bool,
    /// Path to output file (if successful).
    pub output_path: Option<PathBuf>,
    /// Error message (if failed).
    pub error: Option<String>,
    /// Steps that completed.
    pub steps_completed: Vec<String>,
    /// Steps that were skipped.
    pub steps_skipped: Vec<String>,
}

impl JobResult {
    /// Create a successful result.
    pub fn success(job_id: String, output_path: PathBuf, run_result: PipelineRunResult) -> Self {
        Self {
            job_id,
            success: true,
            output_path: Some(output_path),
            error: None,
            steps_completed: run_result.steps_completed,
            steps_skipped: run_result.steps_skipped,
        }
    }

    /// Create a failed result.
    pub fn failure(job_id: String, error: impl Into<String>) -> Self {
        Self {
            job_id,
            success: false,
            output_path: None,
            error: Some(error.into()),
            steps_completed: Vec::new(),
            steps_skipped: Vec::new(),
        }
    }
}

/// Processor for running jobs from the queue through the pipeline.
///
/// The QueueProcessor is responsible for:
/// - Converting JobQueueEntry to JobSpec/Context
/// - Creating and running the pipeline
/// - Collecting results
///
/// # Example
///
/// ```ignore
/// let processor = QueueProcessor::new(settings);
/// let result = processor.process_job(&job_entry, log_callback, progress_callback)?;
/// ```
pub struct QueueProcessor {
    /// Application settings.
    settings: Settings,
    /// Directory for log files.
    log_dir: PathBuf,
    /// Directory for job working files.
    work_dir: PathBuf,
    /// Output directory for final files.
    output_dir: PathBuf,
}

impl QueueProcessor {
    /// Create a new queue processor.
    ///
    /// # Arguments
    /// * `settings` - Application settings
    /// * `log_dir` - Directory for log files
    /// * `work_dir` - Directory for job working files (temp)
    /// * `output_dir` - Directory for final output files
    pub fn new(
        settings: Settings,
        log_dir: PathBuf,
        work_dir: PathBuf,
        output_dir: PathBuf,
    ) -> Self {
        Self {
            settings,
            log_dir,
            work_dir,
            output_dir,
        }
    }

    /// Process a single job from the queue.
    ///
    /// Converts the job entry to a pipeline context, runs the standard
    /// pipeline, and returns the result.
    ///
    /// # Arguments
    /// * `entry` - The job queue entry to process
    /// * `gui_callback` - Optional callback for GUI log output
    /// * `progress_callback` - Optional callback for progress updates
    pub fn process_job(
        &self,
        entry: &JobQueueEntry,
        gui_callback: Option<GuiLogCallback>,
        progress_callback: Option<ProgressCallback>,
    ) -> JobResult {
        // Validate job has required data
        if entry.status != JobQueueStatus::Configured {
            return JobResult::failure(
                entry.id.clone(),
                format!("Job is not configured (status: {:?})", entry.status),
            );
        }

        let layout = match &entry.layout {
            Some(l) => l,
            None => {
                return JobResult::failure(entry.id.clone(), "Job has no layout configured");
            }
        };

        // Create job-specific work directory
        let job_work_dir = self.work_dir.join(&entry.id);
        if let Err(e) = std::fs::create_dir_all(&job_work_dir) {
            return JobResult::failure(
                entry.id.clone(),
                format!("Failed to create work directory: {}", e),
            );
        }

        // Create logger
        let logger = match JobLogger::new(
            &entry.name,
            &self.log_dir,
            LogConfig::default(),
            gui_callback,
        ) {
            Ok(l) => Arc::new(l),
            Err(e) => {
                return JobResult::failure(
                    entry.id.clone(),
                    format!("Failed to create logger: {}", e),
                );
            }
        };

        // Build JobSpec from entry
        let job_spec = JobSpec {
            sources: entry.sources.clone(),
            manual_layout: Some(layout.to_job_spec_format()),
            attachment_sources: layout.attachment_sources.clone(),
        };

        // Create context
        let mut ctx = Context::new(
            job_spec,
            self.settings.clone(),
            &entry.name,
            job_work_dir,
            self.output_dir.clone(),
            logger,
        );

        // Add progress callback if provided
        if let Some(callback) = progress_callback {
            ctx = ctx.with_progress_callback(callback);
        }

        // Create job state
        let mut state = JobState::new(&entry.id);

        // Create and run pipeline
        let pipeline = create_standard_pipeline();

        logger_info(&ctx, &format!("Starting job: {}", entry.name));
        logger_info(
            &ctx,
            &format!("Sources: {} configured", entry.sources.len()),
        );
        logger_info(
            &ctx,
            &format!("Tracks: {} in layout", layout.final_tracks.len()),
        );

        match pipeline.run(&ctx, &mut state) {
            Ok(run_result) => {
                // Get output path from mux result
                let output_path = state
                    .mux
                    .as_ref()
                    .map(|m| m.output_path.clone())
                    .unwrap_or_else(|| self.output_dir.join(format!("{}.mkv", entry.name)));

                logger_info(&ctx, &format!("Job completed: {}", output_path.display()));
                JobResult::success(entry.id.clone(), output_path, run_result)
            }
            Err(e) => {
                let error_msg = format!("Pipeline failed: {}", e);
                ctx.logger.error(&error_msg);
                JobResult::failure(entry.id.clone(), error_msg)
            }
        }
    }

    /// Process multiple jobs sequentially.
    ///
    /// Processes each job in order, collecting results. If a cancel handle
    /// is provided, processing can be stopped between jobs.
    ///
    /// # Arguments
    /// * `entries` - Jobs to process
    /// * `gui_callback_factory` - Factory to create GUI callbacks per job
    /// * `progress_callback_factory` - Factory to create progress callbacks per job
    /// * `cancel_handle` - Optional handle to cancel processing
    pub fn process_queue<F, G>(
        &self,
        entries: &[&JobQueueEntry],
        gui_callback_factory: F,
        progress_callback_factory: G,
        cancel_handle: Option<&CancelHandle>,
    ) -> Vec<JobResult>
    where
        F: Fn(&str) -> Option<GuiLogCallback>,
        G: Fn(&str) -> Option<ProgressCallback>,
    {
        let mut results = Vec::with_capacity(entries.len());

        for (i, entry) in entries.iter().enumerate() {
            // Check for cancellation
            if let Some(handle) = cancel_handle {
                if handle.is_cancelled() {
                    tracing::info!("Queue processing cancelled at job {}/{}", i + 1, entries.len());
                    break;
                }
            }

            tracing::info!(
                "Processing job {}/{}: {}",
                i + 1,
                entries.len(),
                entry.name
            );

            let gui_callback = gui_callback_factory(&entry.id);
            let progress_callback = progress_callback_factory(&entry.id);

            let result = self.process_job(entry, gui_callback, progress_callback);
            results.push(result);
        }

        results
    }

    /// Get a cancel handle for the current pipeline.
    ///
    /// Note: This creates a new pipeline each time, so the handle is only
    /// valid for the next `process_job` call if used synchronously.
    pub fn create_cancel_handle(&self) -> CancelHandle {
        create_standard_pipeline().cancel_handle()
    }
}

/// Helper to log info through context logger.
fn logger_info(ctx: &Context, msg: &str) {
    ctx.logger.info(msg);
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    #[test]
    fn job_result_success() {
        let run_result = PipelineRunResult {
            steps_completed: vec!["Analyze".to_string(), "Mux".to_string()],
            steps_skipped: vec!["Extract".to_string()],
        };

        let result = JobResult::success(
            "job-123".to_string(),
            PathBuf::from("/output/file.mkv"),
            run_result,
        );

        assert!(result.success);
        assert_eq!(result.job_id, "job-123");
        assert!(result.output_path.is_some());
        assert!(result.error.is_none());
        assert_eq!(result.steps_completed.len(), 2);
    }

    #[test]
    fn job_result_failure() {
        let result = JobResult::failure("job-456".to_string(), "Something went wrong");

        assert!(!result.success);
        assert_eq!(result.job_id, "job-456");
        assert!(result.output_path.is_none());
        assert!(result.error.is_some());
    }
}
