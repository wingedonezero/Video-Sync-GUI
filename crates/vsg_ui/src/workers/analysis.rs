//! Analysis worker - runs audio correlation in background
//!
//! Calls vsg_core analysis functions and reports progress back via messages.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use relm4::Sender;

use vsg_core::config::ConfigManager;
use vsg_core::logging::{GuiLogCallback, JobLoggerBuilder, LogConfig};
use vsg_core::models::JobSpec;
use vsg_core::orchestrator::{AnalyzeStep, Context, JobState, Pipeline};

use crate::windows::main_window::{AnalysisResult, MainWindowMsg};

/// Run analysis in background, sending progress/results via sender
pub fn run_analysis(
    source1: PathBuf,
    source2: PathBuf,
    source3: Option<PathBuf>,
    config: Arc<Mutex<ConfigManager>>,
    sender: Sender<MainWindowMsg>,
) {
    // Get job name from source1 filename (like Python does)
    let job_name = source1
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "analysis".to_string());

    // Build sources map (Source 1, Source 2, etc.)
    let mut sources = HashMap::new();
    sources.insert("Source 1".to_string(), source1);
    sources.insert("Source 2".to_string(), source2);

    if let Some(path) = source3 {
        sources.insert("Source 3".to_string(), path);
    }

    // Build job spec
    let job_spec = JobSpec::new(sources);

    // Get settings from config
    // Log goes to output_folder (same as job logs), not logs_folder
    let (settings, output_dir, temp_dir) = {
        let cfg = config.lock().unwrap();
        (
            cfg.settings().clone(),
            PathBuf::from(&cfg.settings().paths.output_folder),
            PathBuf::from(&cfg.settings().paths.temp_root),
        )
    };

    // Log start
    let _ = sender.send(MainWindowMsg::AnalysisLog(format!(
        "Analyzing {} sources...",
        job_spec.sources.len()
    )));

    // Work directory for analyze-only (nothing actually written here)
    let work_dir = temp_dir.join("quick-analysis");

    // Create logger with GUI callback
    // Log file goes to output_folder with source1's name (like Python)
    let log_sender = sender.clone();
    let gui_callback: GuiLogCallback = Box::new(move |msg| {
        let _ = log_sender.send(MainWindowMsg::AnalysisLog(msg.to_string()));
    });

    let logger = match JobLoggerBuilder::new(&job_name, &output_dir)
        .config(LogConfig::default())
        .gui_callback(gui_callback)
        .build()
    {
        Ok(l) => Arc::new(l),
        Err(e) => {
            let _ = sender.send(MainWindowMsg::AnalysisComplete(Err(format!(
                "Failed to create logger: {}",
                e
            ))));
            return;
        }
    };

    // Set up progress callback
    let progress_sender = sender.clone();
    let progress_callback: vsg_core::orchestrator::ProgressCallback =
        Box::new(move |_step: &str, percent: u32, message: &str| {
            let _ = progress_sender.send(MainWindowMsg::AnalysisProgress {
                progress: percent as f64 / 100.0,
                message: message.to_string(),
            });
        });

    // Create pipeline context with progress callback
    let context = Context::new(
        job_spec,
        settings,
        &job_name,
        work_dir.clone(),
        output_dir, // output goes to output_folder
        logger,
    )
    .with_progress_callback(progress_callback);

    let mut state = JobState::new(&job_name);

    // Create pipeline with just analyze step
    let pipeline = Pipeline::new().with_step(AnalyzeStep::new());

    // Run pipeline
    match pipeline.run(&context, &mut state) {
        Ok(_result) => {
            // Extract delays from state
            if let Some(ref analysis_output) = state.analysis {
                let _ = sender.send(MainWindowMsg::AnalysisComplete(Ok(AnalysisResult {
                    delays: analysis_output.delays.clone(),
                })));
            } else {
                let _ = sender.send(MainWindowMsg::AnalysisComplete(Err(
                    "Analysis completed but no results available".to_string(),
                )));
            }
        }
        Err(e) => {
            let _ = sender.send(MainWindowMsg::AnalysisComplete(Err(format!(
                "Analysis failed: {}",
                e
            ))));
        }
    }
}
