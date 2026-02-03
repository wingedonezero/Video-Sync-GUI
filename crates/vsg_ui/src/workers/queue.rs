//! Queue processing worker - runs jobs from the queue in background
//!
//! Takes job IDs, retrieves entries from the queue, and processes them
//! through the standard pipeline, sending progress updates to the UI.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use relm4::Sender;

use vsg_core::config::ConfigManager;
use vsg_core::jobs::JobQueue;
use vsg_core::logging::GuiLogCallback;
use vsg_core::orchestrator::ProgressCallback;

use crate::windows::main_window::MainWindowMsg;

/// Run queue processing in background, sending progress/results via sender.
///
/// # Arguments
/// * `job_ids` - IDs of jobs to process
/// * `config` - Configuration manager
/// * `sender` - Channel to send messages back to UI
///
/// The job queue is loaded from disk (persisted in temp folder).
pub fn run_queue_processing(
    job_ids: Vec<String>,
    config: Arc<Mutex<ConfigManager>>,
    sender: Sender<MainWindowMsg>,
) {
    // Get settings and directories from config
    let (settings, log_dir, temp_dir, output_dir) = {
        let cfg = config.lock().unwrap();
        (
            cfg.settings().clone(),
            cfg.logs_folder(),
            PathBuf::from(&cfg.settings().paths.temp_root),
            PathBuf::from(&cfg.settings().paths.output_folder),
        )
    };

    // Load job queue from disk (it's persisted in temp folder)
    let mut job_queue = JobQueue::new(&temp_dir);

    // Log start with queue info
    let _ = sender.send(MainWindowMsg::QueueLog(format!(
        "Loading queue from: {}/queue.json ({} jobs found)",
        temp_dir.display(),
        job_queue.len()
    )));
    let _ = sender.send(MainWindowMsg::QueueLog(format!(
        "Starting queue processing for {} jobs...",
        job_ids.len()
    )));

    // Create queue processor
    let processor = vsg_core::orchestrator::QueueProcessor::new(
        settings,
        log_dir,
        temp_dir.clone(),
        output_dir,
    );

    // Track results
    let mut succeeded = 0;
    let mut failed = 0;
    let total = job_ids.len();

    // Process each job
    for (i, job_id) in job_ids.iter().enumerate() {
        // Get job entry from queue
        let entry = match job_queue.get_by_id(job_id) {
            Some(e) => {
                let _ = sender.send(MainWindowMsg::QueueLog(format!(
                    "Found job {}: status={:?}, layout_id={}",
                    job_id,
                    e.status,
                    e.layout_id
                )));
                e.clone()
            }
            None => {
                let _ = sender.send(MainWindowMsg::QueueLog(format!(
                    "Job {} not found in queue, skipping",
                    job_id
                )));
                failed += 1;
                continue;
            }
        };

        // Notify job started
        let _ = sender.send(MainWindowMsg::QueueJobStarted {
            job_id: job_id.clone(),
            job_name: entry.name.clone(),
        });

        let _ = sender.send(MainWindowMsg::QueueLog(format!(
            "[{}/{}] Processing: {}",
            i + 1,
            total,
            entry.name
        )));

        // Update job status to Processing
        if let Some(job) = job_queue.get_by_id_mut(job_id) {
            job.status = vsg_core::jobs::JobQueueStatus::Processing;
        }
        let _ = job_queue.save();

        // Create GUI callback for this job
        let log_sender = sender.clone();
        let gui_callback: GuiLogCallback = Box::new(move |msg| {
            let _ = log_sender.send(MainWindowMsg::QueueLog(msg.to_string()));
        });

        // Create progress callback for this job
        let progress_sender = sender.clone();
        let progress_job_id = job_id.clone();
        let progress_callback: ProgressCallback =
            Box::new(move |_step: &str, percent: u32, message: &str| {
                let _ = progress_sender.send(MainWindowMsg::QueueJobProgress {
                    job_id: progress_job_id.clone(),
                    progress: percent as f64 / 100.0,
                    message: message.to_string(),
                });
            });

        // Process the job
        let result = processor.process_job(&entry, Some(gui_callback), Some(progress_callback));

        // Update job status based on result
        if let Some(job) = job_queue.get_by_id_mut(job_id) {
            if result.success {
                job.status = vsg_core::jobs::JobQueueStatus::Complete;
                job.error_message = None;
            } else {
                job.status = vsg_core::jobs::JobQueueStatus::Error;
                job.error_message = result.error.clone();
            }
        }
        let _ = job_queue.save();

        // Notify job completed
        let _ = sender.send(MainWindowMsg::QueueJobComplete {
            job_id: job_id.clone(),
            success: result.success,
            output_path: result.output_path.clone(),
            error: result.error.clone(),
        });

        if result.success {
            let _ = sender.send(MainWindowMsg::QueueLog(format!(
                "Job completed: {} -> {}",
                entry.name,
                result
                    .output_path
                    .as_ref()
                    .map(|p| p.display().to_string())
                    .unwrap_or_default()
            )));
            succeeded += 1;
        } else {
            let _ = sender.send(MainWindowMsg::QueueLog(format!(
                "Job failed: {} - {}",
                entry.name,
                result.error.unwrap_or_default()
            )));
            failed += 1;
        }
    }

    // Notify all processing complete
    let _ = sender.send(MainWindowMsg::QueueProcessingComplete {
        total,
        succeeded,
        failed,
    });

    let _ = sender.send(MainWindowMsg::QueueLog(format!(
        "Queue processing complete: {}/{} succeeded, {} failed",
        succeeded, total, failed
    )));
}
