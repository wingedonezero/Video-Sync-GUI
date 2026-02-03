//! Queue processing worker - runs jobs from the queue in background
//!
//! Takes job entries and processes them through the standard pipeline,
//! sending progress updates to the UI.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use relm4::Sender;

use vsg_core::config::ConfigManager;
use vsg_core::jobs::{JobQueueEntry, LayoutManager};
use vsg_core::logging::GuiLogCallback;
use vsg_core::orchestrator::ProgressCallback;

use crate::windows::main_window::MainWindowMsg;

/// Run queue processing in background, sending progress/results via sender.
///
/// # Arguments
/// * `job_entries` - Job entries to process (passed directly from UI, no queue.json)
/// * `config` - Configuration manager
/// * `sender` - Channel to send messages back to UI
pub fn run_queue_processing(
    job_entries: Vec<JobQueueEntry>,
    config: Arc<Mutex<ConfigManager>>,
    sender: Sender<MainWindowMsg>,
) {
    // Get settings and directories from config
    let (settings, temp_dir, output_dir) = {
        let cfg = config.lock().unwrap();
        (
            cfg.settings().clone(),
            PathBuf::from(&cfg.settings().paths.temp_root),
            PathBuf::from(&cfg.settings().paths.output_folder),
        )
    };

    // Create layout manager for cleanup at end
    let layout_manager = LayoutManager::new(&temp_dir.join("job_layouts"));

    let _ = sender.send(MainWindowMsg::QueueLog(format!(
        "Starting queue processing for {} jobs...",
        job_entries.len()
    )));

    // Create queue processor
    // NOTE: log_dir is set to output_dir to match original Python behavior
    // (logs are written directly to the output folder as {job_name}.log)
    let processor = vsg_core::orchestrator::QueueProcessor::new(
        settings,
        output_dir.clone(), // logs go to output directory like original Python
        temp_dir.clone(),
        output_dir,
    );

    // Track results
    let mut succeeded = 0;
    let mut failed = 0;
    let total = job_entries.len();

    // Process each job
    for (i, entry) in job_entries.iter().enumerate() {
        let _ = sender.send(MainWindowMsg::QueueLog(format!(
            "Job {}: layout_id={}",
            entry.id,
            entry.layout_id
        )));

        // Notify job started
        let _ = sender.send(MainWindowMsg::QueueJobStarted {
            job_id: entry.id.clone(),
            job_name: entry.name.clone(),
        });

        let _ = sender.send(MainWindowMsg::QueueLog(format!(
            "[{}/{}] Processing: {}",
            i + 1,
            total,
            entry.name
        )));

        // Create GUI callback for this job
        let log_sender = sender.clone();
        let gui_callback: GuiLogCallback = Box::new(move |msg| {
            let _ = log_sender.send(MainWindowMsg::QueueLog(msg.to_string()));
        });

        // Create progress callback for this job
        let progress_sender = sender.clone();
        let progress_job_id = entry.id.clone();
        let progress_callback: ProgressCallback =
            Box::new(move |_step: &str, percent: u32, message: &str| {
                let _ = progress_sender.send(MainWindowMsg::QueueJobProgress {
                    job_id: progress_job_id.clone(),
                    progress: percent as f64 / 100.0,
                    message: message.to_string(),
                });
            });

        // Process the job (layout loaded from job_layouts/{layout_id}.json by QueueProcessor)
        let result = processor.process_job(entry, Some(gui_callback), Some(progress_callback));

        // Notify job completed
        let _ = sender.send(MainWindowMsg::QueueJobComplete {
            job_id: entry.id.clone(),
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

    // Clean up all layout files after processing completes
    if let Err(e) = layout_manager.cleanup_all() {
        let _ = sender.send(MainWindowMsg::QueueLog(format!(
            "Warning: Failed to cleanup layout files: {}",
            e
        )));
    } else {
        let _ = sender.send(MainWindowMsg::QueueLog(
            "Cleaned up all job layout files.".to_string()
        ));
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
