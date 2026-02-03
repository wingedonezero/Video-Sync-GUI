//! Batch processing handlers for running jobs from the queue.

use std::fs::{self, File};
use std::io::{Read as IoRead, Write as IoWrite};
use std::path::Path;

use iced::Task;

use vsg_core::jobs::{JobQueueEntry, JobQueueStatus};

use crate::app::{App, Message};
use super::helpers::run_job_pipeline;

impl App {
    /// Handle StartBatchProcessing - receive jobs from queue and begin processing.
    pub fn handle_start_batch_processing(&mut self, jobs: Vec<JobQueueEntry>) -> Task<Message> {
        let job_count = jobs.len();
        tracing::info!("Starting batch processing of {} jobs", job_count);

        // Store jobs in batch processing state
        self.processing_jobs = jobs;
        self.current_job_index = 0;
        self.total_jobs = job_count;
        self.is_processing = true;
        self.batch_status = format!("Starting batch: 0 of {} jobs", job_count);

        // Close the job queue window
        let close_task = self.close_job_queue_window();

        // Chain: close window, then start processing first job
        Task::batch([close_task, Task::done(Message::ProcessNextJob)])
    }

    /// Handle ProcessNextJob - process the next job in the batch.
    pub fn handle_process_next_job(&mut self) -> Task<Message> {
        // Check if we've processed all jobs
        if self.current_job_index >= self.total_jobs {
            return Task::done(Message::BatchCompleted);
        }

        // Clone all data we need from the job before any mutable operations
        let job = &self.processing_jobs[self.current_job_index];
        let job_name = job.name.clone();
        let job_idx = self.current_job_index;
        let layout_id = job.layout_id.clone();
        let sources = job.sources.clone();
        // Drop the reference to job
        drop(job);

        tracing::info!(
            "Processing job {} of {}: {} (layout_id: {})",
            job_idx + 1,
            self.total_jobs,
            job_name,
            layout_id
        );

        // Update status
        self.batch_status = format!(
            "Processing job {} of {}: {}",
            job_idx + 1,
            self.total_jobs,
            job_name
        );
        self.status_text = format!("Processing: {}", job_name);
        self.progress_value = 0.0;

        // Update job status in queue to Processing
        {
            let mut q = self.job_queue.lock().unwrap();
            q.set_status(job_idx, JobQueueStatus::Processing);
            if let Err(e) = q.save() {
                tracing::warn!("Failed to save queue status: {}", e);
            }
        }

        // Load the layout from disk
        let layout = {
            let lm = self.layout_manager.lock().unwrap();
            match lm.load_layout(&layout_id) {
                Ok(Some(layout)) => {
                    tracing::debug!("Loaded layout for job: {}", layout_id);
                    Some(layout)
                }
                Ok(None) => {
                    tracing::warn!("No layout found for job: {}", layout_id);
                    None
                }
                Err(e) => {
                    tracing::error!("Failed to load layout for job {}: {}", layout_id, e);
                    None
                }
            }
        };

        // Log job info
        if let Some(ref layout) = layout {
            self.append_log(&format!(
                "Job {} of {}: {} ({} tracks configured)",
                job_idx + 1,
                self.total_jobs,
                job_name,
                layout.final_tracks.len()
            ));
        } else {
            self.append_log(&format!(
                "Job {} of {}: {} (no layout - using defaults)",
                job_idx + 1,
                self.total_jobs,
                job_name
            ));
        }

        // Get settings
        let settings = {
            let cfg = self.config.lock().unwrap();
            cfg.settings().clone()
        };

        self.append_log(&format!("  -> Running pipeline for: {}", job_name));

        // Run the job pipeline asynchronously
        Task::perform(
            async move { run_job_pipeline(job_name, sources, layout, settings).await },
            move |result| match result {
                Ok(output_path) => Message::JobCompleted {
                    job_idx,
                    success: true,
                    error: Some(format!("Output: {}", output_path.display())),
                },
                Err(e) => Message::JobCompleted {
                    job_idx,
                    success: false,
                    error: Some(e),
                },
            },
        )
    }

    /// Handle JobCompleted - a single job finished, move to next.
    pub fn handle_job_completed(
        &mut self,
        job_idx: usize,
        success: bool,
        error: Option<String>,
    ) -> Task<Message> {
        let job_name = if job_idx < self.processing_jobs.len() {
            self.processing_jobs[job_idx].name.clone()
        } else {
            format!("Job {}", job_idx + 1)
        };

        // Prepare log message outside the lock
        let log_msg = if success {
            tracing::info!("Job completed successfully: {}", job_name);
            format!("  -> Complete: {}", job_name)
        } else {
            let err_msg = error.clone().unwrap_or_else(|| "Unknown error".to_string());
            tracing::error!("Job failed: {} - {}", job_name, err_msg);
            format!("  -> Failed: {} - {}", job_name, err_msg)
        };

        // Update job status in queue (separate scope to release lock)
        {
            let mut q = self.job_queue.lock().unwrap();
            if success {
                q.set_status(job_idx, JobQueueStatus::Complete);
            } else {
                let err_msg = error.unwrap_or_else(|| "Unknown error".to_string());
                q.set_error(job_idx, err_msg);
            }
            if let Err(e) = q.save() {
                tracing::warn!("Failed to save queue status: {}", e);
            }
        }

        // Log after releasing the lock
        self.append_log(&log_msg);

        // Move to next job
        self.current_job_index += 1;
        Task::done(Message::ProcessNextJob)
    }

    /// Handle BatchCompleted - all jobs finished.
    pub fn handle_batch_completed(&mut self) -> Task<Message> {
        self.is_processing = false;

        // Count results
        let completed = self
            .processing_jobs
            .iter()
            .filter(|j| j.status == JobQueueStatus::Complete)
            .count();
        let failed = self
            .processing_jobs
            .iter()
            .filter(|j| j.status == JobQueueStatus::Error)
            .count();

        let summary = if failed == 0 {
            format!("Batch complete: {} jobs processed successfully", completed)
        } else {
            format!(
                "Batch complete: {} succeeded, {} failed",
                completed, failed
            )
        };

        tracing::info!("{}", summary);
        self.batch_status = summary.clone();
        self.status_text = summary.clone();
        self.append_log(&format!("\n{}", summary));

        // Archive logs if enabled
        if self.archive_logs {
            let output_folder = {
                let cfg = self.config.lock().unwrap();
                cfg.settings().paths.output_folder.clone()
            };
            match archive_logs_for_batch(Path::new(&output_folder)) {
                Ok(Some(archive_path)) => {
                    self.append_log(&format!("Logs archived to: {}", archive_path.display()));
                    tracing::info!("Logs archived to: {}", archive_path.display());
                }
                Ok(None) => {
                    tracing::debug!("No log files to archive");
                }
                Err(e) => {
                    self.append_log(&format!("Failed to archive logs: {}", e));
                    tracing::warn!("Failed to archive logs: {}", e);
                }
            }
        }

        // Clean up layouts (like Qt's cleanup_all after batch)
        {
            let lm = self.layout_manager.lock().unwrap();
            if let Err(e) = lm.cleanup_all() {
                tracing::warn!("Failed to cleanup layouts: {}", e);
            }
        }

        // Clear batch state
        self.processing_jobs.clear();
        self.current_job_index = 0;
        self.total_jobs = 0;
        self.progress_value = 0.0;

        Task::none()
    }
}

/// Archive all .log files in the output directory to a timestamped zip file.
///
/// Returns the path to the created archive, or None if there were no log files.
fn archive_logs_for_batch(output_dir: &Path) -> Result<Option<std::path::PathBuf>, String> {
    // Collect all .log files in the output directory
    let log_files: Vec<_> = fs::read_dir(output_dir)
        .map_err(|e| format!("Failed to read output directory: {}", e))?
        .filter_map(|entry| entry.ok())
        .filter(|entry| {
            entry.path().extension().map_or(false, |ext| ext == "log")
        })
        .collect();

    if log_files.is_empty() {
        return Ok(None);
    }

    // Create archive filename with timestamp
    let timestamp = chrono::Local::now().format("%Y-%m-%d_%H-%M-%S");
    let archive_name = format!("logs_{}.zip", timestamp);
    let archive_path = output_dir.join(&archive_name);

    // Create zip archive
    let file = File::create(&archive_path)
        .map_err(|e| format!("Failed to create archive file: {}", e))?;
    let mut zip = zip::ZipWriter::new(file);
    let options = zip::write::SimpleFileOptions::default()
        .compression_method(zip::CompressionMethod::Deflated)
        .unix_permissions(0o644);

    for entry in &log_files {
        let path = entry.path();
        let file_name = path.file_name()
            .and_then(|n| n.to_str())
            .ok_or_else(|| "Invalid log filename".to_string())?;

        // Read file contents
        let mut file = File::open(&path)
            .map_err(|e| format!("Failed to open log file {}: {}", file_name, e))?;
        let mut contents = Vec::new();
        file.read_to_end(&mut contents)
            .map_err(|e| format!("Failed to read log file {}: {}", file_name, e))?;

        // Add to archive
        zip.start_file(file_name, options)
            .map_err(|e| format!("Failed to add {} to archive: {}", file_name, e))?;
        zip.write_all(&contents)
            .map_err(|e| format!("Failed to write {} to archive: {}", file_name, e))?;
    }

    zip.finish()
        .map_err(|e| format!("Failed to finalize archive: {}", e))?;

    // Delete the original log files after successful archiving
    for entry in &log_files {
        if let Err(e) = fs::remove_file(entry.path()) {
            tracing::warn!("Failed to delete log file {}: {}", entry.path().display(), e);
        }
    }

    Ok(Some(archive_path))
}
