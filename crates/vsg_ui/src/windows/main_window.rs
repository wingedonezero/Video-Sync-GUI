//! Main window logic.
//!
//! This module contains all the callback handlers and helper functions
//! for the main application window.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::mpsc;
use std::sync::{Arc, Mutex};
use std::thread;

use slint::ComponentHandle;
use vsg_core::config::{ConfigManager, Settings};
use vsg_core::logging::{GuiLogCallback, JobLogger, LogConfig};
use vsg_core::models::JobSpec;
use vsg_core::orchestrator::{AnalyzeStep, Context, JobState, Pipeline};

use crate::ui::{MainWindow, SettingsWindow};
use crate::windows::settings_window::{populate_settings_window, read_settings_from_window, setup_settings_browse_buttons};

/// Set up all callbacks and handlers for the main window.
///
/// This wires up button clicks, source browsing, analysis, and
/// settings window integration.
pub fn setup_main_window(
    main_window: &MainWindow,
    config: Arc<Mutex<ConfigManager>>,
) {
    // Set archive_logs from config
    {
        let cfg = config.lock().unwrap();
        main_window.set_archive_logs(cfg.settings().logging.archive_logs);
    }

    setup_settings_button(main_window, Arc::clone(&config));
    setup_queue_jobs_button(main_window);
    setup_browse_buttons(main_window);
    setup_source_path_changed(main_window);
    setup_analyze_only_button(main_window, Arc::clone(&config));
}

/// Set up the Settings button handler.
fn setup_settings_button(main_window: &MainWindow, config: Arc<Mutex<ConfigManager>>) {
    let window_weak = main_window.as_weak();
    let config_clone = Arc::clone(&config);

    main_window.on_settings_clicked(move || {
        if let Some(window) = window_weak.upgrade() {
            append_log(&window, "Opening settings...");

            // Create and show settings window
            match SettingsWindow::new() {
                Ok(settings) => {
                    // Populate settings from config
                    {
                        let cfg = config_clone.lock().unwrap();
                        populate_settings_window(&settings, cfg.settings());
                    }

                    // Set up browse buttons
                    setup_settings_browse_buttons(&settings);

                    // Wire up cancel button to close
                    let settings_weak = settings.as_weak();
                    settings.on_cancel_clicked(move || {
                        if let Some(s) = settings_weak.upgrade() {
                            s.hide().ok();
                        }
                    });

                    // Wire up save button
                    let settings_weak = settings.as_weak();
                    let config_for_save = Arc::clone(&config_clone);
                    let window_for_save = window.as_weak();
                    settings.on_save_clicked(move || {
                        if let Some(s) = settings_weak.upgrade() {
                            // Read values from UI and save
                            let mut cfg = config_for_save.lock().unwrap();
                            read_settings_from_window(&s, cfg.settings_mut());

                            if let Err(e) = cfg.save() {
                                if let Some(w) = window_for_save.upgrade() {
                                    append_log(&w, &format!("Failed to save settings: {}", e));
                                }
                            } else if let Some(w) = window_for_save.upgrade() {
                                append_log(&w, "Settings saved.");
                            }

                            s.hide().ok();
                        }
                    });

                    // Show the settings window
                    if let Err(e) = settings.show() {
                        append_log(&window, &format!("Failed to show settings: {}", e));
                    }
                }
                Err(e) => {
                    append_log(&window, &format!("Failed to create settings window: {}", e));
                }
            }
        }
    });
}

/// Set up the Queue Jobs button handler.
fn setup_queue_jobs_button(main_window: &MainWindow) {
    let window_weak = main_window.as_weak();

    main_window.on_queue_jobs_clicked(move || {
        if let Some(window) = window_weak.upgrade() {
            append_log(&window, "Opening job queue...");
            append_log(&window, "Job queue dialog not yet implemented");
        }
    });
}

/// Set up all source browse buttons.
fn setup_browse_buttons(main_window: &MainWindow) {
    // Browse Source 1
    let window_weak = main_window.as_weak();
    main_window.on_browse_source1(move || {
        if let Some(window) = window_weak.upgrade() {
            if let Some(path) = pick_video_file("Select Source 1 (Reference)") {
                window.set_source1_path(path.to_string_lossy().to_string().into());
                append_log(&window, &format!("Source 1: {}", path.display()));
            }
        }
    });

    // Browse Source 2
    let window_weak = main_window.as_weak();
    main_window.on_browse_source2(move || {
        if let Some(window) = window_weak.upgrade() {
            if let Some(path) = pick_video_file("Select Source 2") {
                window.set_source2_path(path.to_string_lossy().to_string().into());
                append_log(&window, &format!("Source 2: {}", path.display()));
            }
        }
    });

    // Browse Source 3
    let window_weak = main_window.as_weak();
    main_window.on_browse_source3(move || {
        if let Some(window) = window_weak.upgrade() {
            if let Some(path) = pick_video_file("Select Source 3") {
                window.set_source3_path(path.to_string_lossy().to_string().into());
                append_log(&window, &format!("Source 3: {}", path.display()));
            }
        }
    });
}

/// Set up handler for source path changes (from drag-drop or manual edit).
fn setup_source_path_changed(main_window: &MainWindow) {
    let window_weak = main_window.as_weak();

    main_window.on_source_path_changed(move |source_idx, path| {
        if let Some(window) = window_weak.upgrade() {
            // Clean up file:// URL if present (from drag-drop)
            let clean_path = clean_file_url(&path);

            // Update the path in the UI if it was cleaned
            if clean_path != path.as_str() {
                match source_idx {
                    1 => window.set_source1_path(clean_path.clone().into()),
                    2 => window.set_source2_path(clean_path.clone().into()),
                    3 => window.set_source3_path(clean_path.clone().into()),
                    _ => {}
                }
            }

            // Log the change
            if !clean_path.is_empty() {
                append_log(&window, &format!("Source {}: {}", source_idx, clean_path));
            }
        }
    });
}

/// Messages sent from background analysis thread to UI.
enum AnalysisMessage {
    /// Log message to append.
    Log(String),
    /// Progress update (0-100).
    Progress(f32),
    /// Analysis completed successfully.
    Complete {
        delay_source2_ms: Option<i64>,
        delay_source3_ms: Option<i64>,
    },
    /// Analysis failed.
    Failed(String),
}

/// Set up the Analyze Only button handler.
fn setup_analyze_only_button(main_window: &MainWindow, config: Arc<Mutex<ConfigManager>>) {
    let window_weak = main_window.as_weak();
    let config_for_analyze = Arc::clone(&config);

    main_window.on_analyze_only_clicked(move || {
        if let Some(window) = window_weak.upgrade() {
            let source1 = window.get_source1_path().to_string();
            let source2 = window.get_source2_path().to_string();

            if source1.is_empty() || source2.is_empty() {
                append_log(
                    &window,
                    "[WARNING] Please select at least Source 1 and Source 2",
                );
                return;
            }

            let source3 = window.get_source3_path().to_string();

            window.set_status_text("Analyzing...".into());
            window.set_progress_value(0.0);

            append_log(&window, "=== Starting Analysis ===");
            append_log(&window, &format!("Source 1: {}", source1));
            append_log(&window, &format!("Source 2: {}", source2));
            if !source3.is_empty() {
                append_log(&window, &format!("Source 3: {}", source3));
            }

            // Build job spec
            let job_spec = build_job_spec(&source1, &source2, &source3);

            // Get settings
            let settings = {
                let cfg = config_for_analyze.lock().unwrap();
                cfg.settings().clone()
            };

            // Create channel for communication with background thread
            let (tx, rx) = mpsc::channel::<AnalysisMessage>();

            // Spawn background thread for analysis
            thread::spawn(move || {
                // Create callback that sends log messages to UI thread
                let tx_log = tx.clone();
                let log_callback: GuiLogCallback = Box::new(move |msg: &str| {
                    let _ = tx_log.send(AnalysisMessage::Log(msg.to_string()));
                });

                // Send initial progress
                let _ = tx.send(AnalysisMessage::Progress(10.0));

                // Run the analysis pipeline
                let result = run_analyze_only(job_spec, settings, log_callback);

                // Send results
                if result.success {
                    let _ = tx.send(AnalysisMessage::Complete {
                        delay_source2_ms: result.delay_source2_ms,
                        delay_source3_ms: result.delay_source3_ms,
                    });
                } else {
                    let error_msg = result.error.unwrap_or_else(|| "Unknown error".to_string());
                    let _ = tx.send(AnalysisMessage::Failed(error_msg));
                }
            });

            // Set up timer to poll for messages from background thread
            let window_weak_timer = window.as_weak();
            let timer = slint::Timer::default();
            let rx = Arc::new(Mutex::new(Some(rx)));
            let rx_clone = Arc::clone(&rx);

            timer.start(
                slint::TimerMode::Repeated,
                std::time::Duration::from_millis(50),
                move || {
                    if let Some(window) = window_weak_timer.upgrade() {
                        let mut rx_guard = rx_clone.lock().unwrap();
                        if let Some(ref receiver) = *rx_guard {
                            // Process all pending messages
                            loop {
                                match receiver.try_recv() {
                                    Ok(AnalysisMessage::Log(msg)) => {
                                        append_log(&window, &msg);
                                    }
                                    Ok(AnalysisMessage::Progress(pct)) => {
                                        window.set_progress_value(pct);
                                    }
                                    Ok(AnalysisMessage::Complete { delay_source2_ms, delay_source3_ms }) => {
                                        if let Some(delay_ms) = delay_source2_ms {
                                            let delay_str = format!("{} ms", delay_ms);
                                            window.set_delay_source2(delay_str.into());
                                            append_log(&window, &format!("Source 2 delay: {} ms", delay_ms));
                                        }

                                        if let Some(delay_ms) = delay_source3_ms {
                                            let delay_str = format!("{} ms", delay_ms);
                                            window.set_delay_source3(delay_str.into());
                                            append_log(&window, &format!("Source 3 delay: {} ms", delay_ms));
                                        }

                                        window.set_progress_value(100.0);
                                        window.set_status_text("Ready".into());
                                        append_log(&window, "=== Analysis Complete ===");

                                        // Stop the timer by dropping the receiver
                                        *rx_guard = None;
                                        return;
                                    }
                                    Ok(AnalysisMessage::Failed(error_msg)) => {
                                        append_log(&window, &format!("[ERROR] {}", error_msg));
                                        window.set_progress_value(0.0);
                                        window.set_status_text("Analysis Failed".into());

                                        // Stop the timer
                                        *rx_guard = None;
                                        return;
                                    }
                                    Err(mpsc::TryRecvError::Empty) => {
                                        // No more messages, break the loop
                                        break;
                                    }
                                    Err(mpsc::TryRecvError::Disconnected) => {
                                        // Channel closed unexpectedly
                                        append_log(&window, "[ERROR] Analysis thread disconnected unexpectedly");
                                        window.set_status_text("Analysis Failed".into());
                                        *rx_guard = None;
                                        return;
                                    }
                                }
                            }
                        }
                    }
                },
            );

            // Keep timer alive by storing it (it will be dropped when analysis completes)
            // Note: The timer keeps itself alive via the closure
        }
    });
}

// =============================================================================
// Helper Functions
// =============================================================================

/// Append text to the log panel.
pub fn append_log(window: &MainWindow, message: &str) {
    let current = window.get_log_text();
    let new_text = format!("{}{}\n", current, message);
    window.set_log_text(new_text.into());
}

/// Open a file dialog to pick a video file.
fn pick_video_file(title: &str) -> Option<PathBuf> {
    rfd::FileDialog::new()
        .set_title(title)
        .add_filter(
            "Video Files",
            &["mkv", "mp4", "avi", "mov", "webm", "m4v", "ts", "m2ts"],
        )
        .add_filter("All Files", &["*"])
        .pick_file()
}

/// Clean up a file URL (from drag-drop) to a regular path.
///
/// Handles text/uri-list format (multiple URIs separated by newlines)
/// and file:// URLs with URL-encoded characters.
fn clean_file_url(url: &str) -> String {
    // text/uri-list can contain multiple URIs separated by \r\n or \n
    // Lines starting with # are comments (per RFC 2483)
    // We take the first valid file:// URI
    let first_uri = url
        .lines()
        .map(|line| line.trim())
        .find(|line| !line.is_empty() && !line.starts_with('#'))
        .unwrap_or("");

    let path = if first_uri.starts_with("file://") {
        // Remove file:// prefix
        let without_prefix = &first_uri[7..];
        // URL decode (handle %20 for spaces, etc.)
        percent_decode(without_prefix)
    } else {
        first_uri.to_string()
    };

    // Trim any trailing whitespace
    path.trim().to_string()
}

/// Simple percent decoding for file paths.
fn percent_decode(input: &str) -> String {
    let mut result = String::with_capacity(input.len());
    let mut chars = input.chars().peekable();

    while let Some(c) = chars.next() {
        if c == '%' {
            // Try to read two hex digits
            let hex: String = chars.by_ref().take(2).collect();
            if hex.len() == 2 {
                if let Ok(byte) = u8::from_str_radix(&hex, 16) {
                    result.push(byte as char);
                    continue;
                }
            }
            // If decoding failed, keep the original
            result.push('%');
            result.push_str(&hex);
        } else {
            result.push(c);
        }
    }

    result
}

/// Build a JobSpec from UI source paths.
fn build_job_spec(source1: &str, source2: &str, source3: &str) -> JobSpec {
    let mut sources = HashMap::new();

    if !source1.is_empty() {
        sources.insert("Source 1".to_string(), PathBuf::from(source1));
    }
    if !source2.is_empty() {
        sources.insert("Source 2".to_string(), PathBuf::from(source2));
    }
    if !source3.is_empty() {
        sources.insert("Source 3".to_string(), PathBuf::from(source3));
    }

    JobSpec::new(sources)
}

/// Create LogConfig from application Settings.
fn log_config_from_settings(settings: &Settings) -> LogConfig {
    LogConfig {
        compact: settings.logging.compact,
        progress_step: settings.logging.progress_step,
        error_tail: settings.logging.error_tail as usize,
        ..LogConfig::default()
    }
}

// =============================================================================
// Analysis Pipeline
// =============================================================================

/// Result of running analysis.
struct AnalysisResult {
    /// Delay for Source 2 in milliseconds.
    delay_source2_ms: Option<i64>,
    /// Delay for Source 3 in milliseconds.
    delay_source3_ms: Option<i64>,
    /// Whether analysis succeeded.
    success: bool,
    /// Error message if failed.
    error: Option<String>,
}

/// Run the analyze-only pipeline.
///
/// This creates the pipeline infrastructure and runs just the Analyze step.
fn run_analyze_only(
    job_spec: JobSpec,
    settings: Settings,
    log_callback: GuiLogCallback,
) -> AnalysisResult {
    // Generate job name from primary source
    let job_name = job_spec
        .sources
        .get("Source 1")
        .map(|p| {
            p.file_stem()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_else(|| "job".to_string())
        })
        .unwrap_or_else(|| "job".to_string());

    // Generate timestamp for unique temp folder
    let timestamp = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);

    // Set up directories
    // Temp folder uses orch_{name}_{timestamp} pattern to avoid conflicts
    let work_dir = PathBuf::from(&settings.paths.temp_root)
        .join(format!("orch_{}_{}", job_name, timestamp));
    let output_dir = PathBuf::from(&settings.paths.output_folder);

    // Create logger with GUI callback
    // Job log goes next to output file, not in .logs folder
    let log_config = log_config_from_settings(&settings);
    let logger = match JobLogger::new(&job_name, &output_dir, log_config, Some(log_callback)) {
        Ok(l) => Arc::new(l),
        Err(e) => {
            tracing::error!("Failed to create job logger for '{}': {}", job_name, e);
            return AnalysisResult {
                delay_source2_ms: None,
                delay_source3_ms: None,
                success: false,
                error: Some(format!("Failed to create logger: {}", e)),
            };
        }
    };

    tracing::info!("Starting analysis for job '{}'", job_name);

    // Create context
    let ctx = Context::new(
        job_spec,
        settings,
        &job_name,
        work_dir,
        output_dir,
        logger.clone(),
    );

    // Create job state
    let mut state = JobState::new(&job_name);

    // Create pipeline with just the Analyze step
    let pipeline = Pipeline::new().with_step(AnalyzeStep::new());

    // Run the pipeline
    match pipeline.run(&ctx, &mut state) {
        Ok(_result) => {
            // Extract delays from analysis output
            let (delay2, delay3) = if let Some(ref analysis) = state.analysis {
                let d2 = analysis.delays.source_delays_ms.get("Source 2").copied();
                let d3 = analysis.delays.source_delays_ms.get("Source 3").copied();
                (d2, d3)
            } else {
                (None, None)
            };

            tracing::info!(
                "Analysis complete for '{}': Source 2 delay={:?}ms, Source 3 delay={:?}ms",
                job_name, delay2, delay3
            );

            AnalysisResult {
                delay_source2_ms: delay2,
                delay_source3_ms: delay3,
                success: true,
                error: None,
            }
        }
        Err(e) => {
            tracing::error!("Pipeline failed for '{}': {}", job_name, e);
            AnalysisResult {
                delay_source2_ms: None,
                delay_source3_ms: None,
                success: false,
                error: Some(format!("Pipeline failed: {}", e)),
            }
        }
    }
}
