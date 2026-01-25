//! CXX Bridge between vsg_core (Rust) and Qt UI (C++)
//!
//! This crate provides safe FFI bindings using the CXX library.
//! All vsg_core functionality is exposed through this bridge.

use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use tracing_subscriber::layer::SubscriberExt;
use tracing_subscriber::util::SubscriberInitExt;
use tracing_subscriber::{fmt, EnvFilter, Layer};

use vsg_core::analysis::Analyzer;
use vsg_core::config::{ConfigManager, ConfigSection};
use vsg_core::logging::{JobLogger, LogConfig};

// Global message queue for logging from Rust to C++
static LOG_QUEUE: Mutex<VecDeque<String>> = Mutex::new(VecDeque::new());
static PROGRESS: Mutex<(i32, String)> = Mutex::new((0, String::new()));
static INITIALIZED: AtomicBool = AtomicBool::new(false);

#[cxx::bridge(namespace = "vsg")]
mod ffi {
    // =========================================================================
    // Shared Types (accessible from both Rust and C++)
    // =========================================================================

    /// Path-related settings
    #[derive(Debug, Clone, Default)]
    struct PathSettings {
        output_folder: String,
        temp_root: String,
        logs_folder: String,
        last_source1_path: String,
        last_source2_path: String,
    }

    /// Logging settings
    #[derive(Debug, Clone)]
    struct LoggingSettings {
        compact: bool,
        autoscroll: bool,
        error_tail: u32,
        progress_step: u32,
        show_options_pretty: bool,
        show_options_json: bool,
        archive_logs: bool,
    }

    /// Analysis settings (subset - add more as needed)
    #[derive(Debug, Clone)]
    struct AnalysisSettings {
        mode: String,                  // "audio" or "video"
        correlation_method: String,    // "scc", "gcc_phat", etc.
        chunk_count: u32,
        chunk_duration: u32,
        min_match_pct: f64,
        scan_start_pct: f64,
        scan_end_pct: f64,
        use_soxr: bool,
        audio_peak_fit: bool,
        sync_mode: String,             // "positive_only" or "allow_negative"
    }

    /// Chapter settings
    #[derive(Debug, Clone)]
    struct ChapterSettings {
        rename: bool,
        snap_enabled: bool,
        snap_mode: String,             // "previous" or "nearest"
        snap_threshold_ms: u32,
        snap_starts_only: bool,
    }

    /// Post-process settings
    #[derive(Debug, Clone)]
    struct PostProcessSettings {
        disable_track_stats_tags: bool,
        disable_header_compression: bool,
        apply_dialog_norm: bool,
    }

    /// Complete application settings
    #[derive(Debug, Clone)]
    struct AppSettings {
        paths: PathSettings,
        logging: LoggingSettings,
        analysis: AnalysisSettings,
        chapters: ChapterSettings,
        postprocess: PostProcessSettings,
    }

    /// Result of an analysis operation
    #[derive(Debug, Clone)]
    struct AnalysisResult {
        source_index: i32,
        delay_ms: f64,
        confidence: f64,
        success: bool,
        error_message: String,
    }

    /// Result of a job execution
    #[derive(Debug, Clone)]
    struct JobResult {
        success: bool,
        output_path: String,
        steps_completed: Vec<String>,
        steps_skipped: Vec<String>,
        error_message: String,
    }

    /// Job input for running a full pipeline
    #[derive(Debug, Clone)]
    struct JobInput {
        /// Unique job ID
        job_id: String,
        /// Job name (derived from filename)
        job_name: String,
        /// Source paths: index 0 = Source 1, index 1 = Source 2, etc.
        source_paths: Vec<String>,
        /// Track layout as JSON string (serialized ManualLayout)
        layout_json: String,
    }

    /// A discovered job from paths
    #[derive(Debug, Clone)]
    struct DiscoveredJob {
        name: String,
        source_paths: Vec<String>,
    }

    /// Track type enumeration
    #[derive(Debug, Clone)]
    struct TrackInfo {
        id: i32,
        track_type: String,     // "video", "audio", "subtitles"
        codec_id: String,
        language: String,
        name: String,
        is_default: bool,
        is_forced: bool,
        // Audio-specific
        channels: i32,
        sample_rate: i32,
        // Video-specific
        width: i32,
        height: i32,
    }

    /// Attachment info
    #[derive(Debug, Clone)]
    struct AttachmentInfo {
        id: i32,
        file_name: String,
        mime_type: String,
        size: i64,
    }

    /// Media file scan result
    #[derive(Debug, Clone)]
    struct MediaFileInfo {
        path: String,
        tracks: Vec<TrackInfo>,
        attachments: Vec<AttachmentInfo>,
        duration_ms: i64,
        success: bool,
        error_message: String,
    }

    /// Log message from Rust
    #[derive(Debug, Clone)]
    struct LogMessage {
        message: String,
        has_message: bool,
    }

    /// Progress update
    #[derive(Debug, Clone)]
    struct ProgressUpdate {
        percent: i32,
        status: String,
    }

    // =========================================================================
    // Rust functions exposed to C++
    // =========================================================================

    extern "Rust" {
        /// Initialize the bridge - MUST be called before any other bridge function
        /// Sets up logging to both file (app.log) and the message queue
        /// logs_dir: Directory for log files (e.g., ".logs")
        fn bridge_init(logs_dir: &str) -> bool;

        /// Load application settings from config file
        fn bridge_load_settings() -> AppSettings;

        /// Save application settings to config file
        fn bridge_save_settings(settings: &AppSettings) -> bool;

        /// Get the default config file path
        fn bridge_get_config_path() -> String;

        /// Run analysis on the given source paths
        /// Returns a result for each non-reference source
        fn bridge_run_analysis(source_paths: &[String]) -> Vec<AnalysisResult>;

        /// Discover jobs from the given paths (files or directories)
        fn bridge_discover_jobs(paths: &[String]) -> Vec<DiscoveredJob>;

        /// Scan a media file for tracks and attachments
        fn bridge_scan_file(path: &str) -> MediaFileInfo;

        /// Get vsg_core version string
        fn bridge_version() -> String;

        /// Run a full job (analysis + extract + mux)
        fn bridge_run_job(input: &JobInput) -> JobResult;

        // =====================================================================
        // Logging functions
        // =====================================================================

        /// Poll for next log message (returns empty if none)
        fn bridge_poll_log() -> LogMessage;

        /// Get current progress
        fn bridge_get_progress() -> ProgressUpdate;

        /// Push a log message (for internal use and testing)
        fn bridge_log(message: &str);

        /// Clear all pending log messages
        fn bridge_clear_logs();

        /// Clean up temporary files from the given work directory
        fn bridge_cleanup_temp(work_dir: &str) -> bool;
    }
}

// =============================================================================
// Initialization
// =============================================================================

/// Custom tracing layer that sends log messages to the GUI queue
struct GuiLogLayer;

impl<S> Layer<S> for GuiLogLayer
where
    S: tracing::Subscriber,
{
    fn on_event(
        &self,
        event: &tracing::Event<'_>,
        _ctx: tracing_subscriber::layer::Context<'_, S>,
    ) {
        // Format the event
        let mut visitor = MessageVisitor::default();
        event.record(&mut visitor);

        let level = event.metadata().level();
        let prefix = match *level {
            tracing::Level::ERROR => "[ERROR] ",
            tracing::Level::WARN => "[WARNING] ",
            tracing::Level::DEBUG => "[DEBUG] ",
            tracing::Level::TRACE => "[TRACE] ",
            _ => "",
        };

        let message = format!("{}{}", prefix, visitor.message);
        bridge_log(&message);
    }
}

#[derive(Default)]
struct MessageVisitor {
    message: String,
}

impl tracing::field::Visit for MessageVisitor {
    fn record_debug(&mut self, field: &tracing::field::Field, value: &dyn std::fmt::Debug) {
        if field.name() == "message" {
            self.message = format!("{:?}", value);
            // Remove quotes from string debug output
            if self.message.starts_with('"') && self.message.ends_with('"') {
                self.message = self.message[1..self.message.len()-1].to_string();
            }
        }
    }

    fn record_str(&mut self, field: &tracing::field::Field, value: &str) {
        if field.name() == "message" {
            self.message = value.to_string();
        }
    }
}

fn bridge_init(logs_dir: &str) -> bool {
    // Only initialize once
    if INITIALIZED.swap(true, Ordering::SeqCst) {
        bridge_log("[WARNING] Bridge already initialized");
        return true;
    }

    let logs_path = PathBuf::from(logs_dir);

    // Create logs directory if it doesn't exist
    if !logs_path.exists() {
        if let Err(e) = std::fs::create_dir_all(&logs_path) {
            bridge_log(&format!("[ERROR] Failed to create logs directory: {}", e));
            return false;
        }
    }

    // Set up file appender for app.log
    let file_appender = tracing_appender::rolling::never(&logs_path, "app.log");
    let (non_blocking, _guard) = tracing_appender::non_blocking(file_appender);

    // Leak the guard so it lives for the program duration
    // (Not ideal but simple for FFI)
    std::mem::forget(_guard);

    // Build filter
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new("info"));

    // File layer (writes to app.log)
    let file_layer = fmt::layer()
        .with_target(true)
        .with_ansi(false)
        .with_writer(non_blocking);

    // GUI layer (sends to message queue)
    let gui_layer = GuiLogLayer;

    // Build and set the subscriber
    let result = tracing_subscriber::registry()
        .with(filter)
        .with(file_layer)
        .with(gui_layer)
        .try_init();

    match result {
        Ok(_) => {
            tracing::info!("Video Sync GUI initialized");
            tracing::info!("Logs directory: {}", logs_path.display());
            true
        }
        Err(e) => {
            bridge_log(&format!("[ERROR] Failed to initialize logging: {}", e));
            false
        }
    }
}

// =============================================================================
// Logging Implementation
// =============================================================================

fn bridge_log(message: &str) {
    if let Ok(mut queue) = LOG_QUEUE.lock() {
        queue.push_back(message.to_string());
        // Keep queue bounded
        while queue.len() > 1000 {
            queue.pop_front();
        }
    }
}

fn bridge_poll_log() -> ffi::LogMessage {
    if let Ok(mut queue) = LOG_QUEUE.lock() {
        if let Some(msg) = queue.pop_front() {
            return ffi::LogMessage {
                message: msg,
                has_message: true,
            };
        }
    }
    ffi::LogMessage {
        message: String::new(),
        has_message: false,
    }
}

fn bridge_clear_logs() {
    if let Ok(mut queue) = LOG_QUEUE.lock() {
        queue.clear();
    }
}

fn bridge_get_progress() -> ffi::ProgressUpdate {
    if let Ok(progress) = PROGRESS.lock() {
        ffi::ProgressUpdate {
            percent: progress.0,
            status: progress.1.clone(),
        }
    } else {
        ffi::ProgressUpdate {
            percent: 0,
            status: String::new(),
        }
    }
}

fn set_progress(percent: i32, status: &str) {
    if let Ok(mut progress) = PROGRESS.lock() {
        *progress = (percent, status.to_string());
    }
}

// =============================================================================
// Config Implementation
// =============================================================================

fn get_config_manager() -> ConfigManager {
    let config_path = dirs_config_path();
    ConfigManager::new(config_path)
}

fn dirs_config_path() -> PathBuf {
    // Use XDG config dir on Linux, fallback to current dir
    if let Some(config_dir) = dirs::config_dir() {
        config_dir.join("video-sync-gui").join("settings.toml")
    } else {
        PathBuf::from("settings.toml")
    }
}

fn bridge_get_config_path() -> String {
    dirs_config_path().to_string_lossy().to_string()
}

fn bridge_version() -> String {
    vsg_core::version().to_string()
}

fn bridge_load_settings() -> ffi::AppSettings {
    let mut manager = get_config_manager();

    if let Err(e) = manager.load_or_create() {
        bridge_log(&format!("[ERROR] Failed to load config: {}", e));
        return default_app_settings();
    }

    let settings = manager.settings();

    ffi::AppSettings {
        paths: ffi::PathSettings {
            output_folder: settings.paths.output_folder.clone(),
            temp_root: settings.paths.temp_root.clone(),
            logs_folder: settings.paths.logs_folder.clone(),
            last_source1_path: settings.paths.last_source1_path.clone(),
            last_source2_path: settings.paths.last_source2_path.clone(),
        },
        logging: ffi::LoggingSettings {
            compact: settings.logging.compact,
            autoscroll: settings.logging.autoscroll,
            error_tail: settings.logging.error_tail,
            progress_step: settings.logging.progress_step,
            show_options_pretty: settings.logging.show_options_pretty,
            show_options_json: settings.logging.show_options_json,
            archive_logs: settings.logging.archive_logs,
        },
        analysis: ffi::AnalysisSettings {
            mode: format!("{:?}", settings.analysis.mode).to_lowercase(),
            correlation_method: format!("{:?}", settings.analysis.correlation_method).to_lowercase(),
            chunk_count: settings.analysis.chunk_count,
            chunk_duration: settings.analysis.chunk_duration,
            min_match_pct: settings.analysis.min_match_pct,
            scan_start_pct: settings.analysis.scan_start_pct,
            scan_end_pct: settings.analysis.scan_end_pct,
            use_soxr: settings.analysis.use_soxr,
            audio_peak_fit: settings.analysis.audio_peak_fit,
            sync_mode: format!("{:?}", settings.analysis.sync_mode).to_lowercase(),
        },
        chapters: ffi::ChapterSettings {
            rename: settings.chapters.rename,
            snap_enabled: settings.chapters.snap_enabled,
            snap_mode: format!("{:?}", settings.chapters.snap_mode).to_lowercase(),
            snap_threshold_ms: settings.chapters.snap_threshold_ms,
            snap_starts_only: settings.chapters.snap_starts_only,
        },
        postprocess: ffi::PostProcessSettings {
            disable_track_stats_tags: settings.postprocess.disable_track_stats_tags,
            disable_header_compression: settings.postprocess.disable_header_compression,
            apply_dialog_norm: settings.postprocess.apply_dialog_norm,
        },
    }
}

fn bridge_save_settings(settings: &ffi::AppSettings) -> bool {
    let mut manager = get_config_manager();

    // Load existing or create new
    if let Err(e) = manager.load_or_create() {
        bridge_log(&format!("[ERROR] Failed to load config for saving: {}", e));
        return false;
    }

    // Update settings
    {
        let s = manager.settings_mut();

        // Paths
        s.paths.output_folder = settings.paths.output_folder.clone();
        s.paths.temp_root = settings.paths.temp_root.clone();
        s.paths.logs_folder = settings.paths.logs_folder.clone();
        s.paths.last_source1_path = settings.paths.last_source1_path.clone();
        s.paths.last_source2_path = settings.paths.last_source2_path.clone();

        // Logging
        s.logging.compact = settings.logging.compact;
        s.logging.autoscroll = settings.logging.autoscroll;
        s.logging.error_tail = settings.logging.error_tail;
        s.logging.progress_step = settings.logging.progress_step;
        s.logging.show_options_pretty = settings.logging.show_options_pretty;
        s.logging.show_options_json = settings.logging.show_options_json;
        s.logging.archive_logs = settings.logging.archive_logs;

        // Analysis - parse string enums back
        // (For now just store, proper enum parsing can be added)
        s.analysis.chunk_count = settings.analysis.chunk_count;
        s.analysis.chunk_duration = settings.analysis.chunk_duration;
        s.analysis.min_match_pct = settings.analysis.min_match_pct;
        s.analysis.scan_start_pct = settings.analysis.scan_start_pct;
        s.analysis.scan_end_pct = settings.analysis.scan_end_pct;
        s.analysis.use_soxr = settings.analysis.use_soxr;
        s.analysis.audio_peak_fit = settings.analysis.audio_peak_fit;

        // Chapters
        s.chapters.rename = settings.chapters.rename;
        s.chapters.snap_enabled = settings.chapters.snap_enabled;
        s.chapters.snap_threshold_ms = settings.chapters.snap_threshold_ms;
        s.chapters.snap_starts_only = settings.chapters.snap_starts_only;

        // Postprocess
        s.postprocess.disable_track_stats_tags = settings.postprocess.disable_track_stats_tags;
        s.postprocess.disable_header_compression = settings.postprocess.disable_header_compression;
        s.postprocess.apply_dialog_norm = settings.postprocess.apply_dialog_norm;
    }

    // Save all sections
    for section in [
        ConfigSection::Paths,
        ConfigSection::Logging,
        ConfigSection::Analysis,
        ConfigSection::Chapters,
        ConfigSection::Postprocess,
    ] {
        if let Err(e) = manager.update_section(section) {
            bridge_log(&format!("[ERROR] Failed to save section {:?}: {}", section, e));
            return false;
        }
    }

    true
}

// =============================================================================
// Analysis Implementation
// =============================================================================

fn bridge_run_analysis(source_paths: &[String]) -> Vec<ffi::AnalysisResult> {
    if source_paths.len() < 2 {
        bridge_log("[ERROR] Need at least 2 sources for analysis");
        return vec![ffi::AnalysisResult {
            source_index: 0,
            delay_ms: 0.0,
            confidence: 0.0,
            success: false,
            error_message: "Need at least 2 sources".to_string(),
        }];
    }

    // Load settings for analysis config
    let mut config_manager = get_config_manager();
    let settings = if config_manager.load_or_create().is_ok() {
        config_manager.settings().clone()
    } else {
        vsg_core::config::Settings::default()
    };

    // Convert paths
    let paths: Vec<PathBuf> = source_paths.iter().map(PathBuf::from).collect();
    let reference = &paths[0];

    // Derive job name from reference file
    let job_name = reference
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "analysis".to_string());

    // Get logs directory from settings
    let logs_dir = PathBuf::from(&settings.paths.logs_folder);

    // Create LogConfig from settings
    let log_config = LogConfig {
        compact: settings.logging.compact,
        progress_step: settings.logging.progress_step,
        error_tail: settings.logging.error_tail as usize,
        ..LogConfig::default()
    };

    // Create GUI callback that feeds our message queue
    let gui_callback: Box<dyn Fn(&str) + Send + Sync> = Box::new(|msg: &str| {
        bridge_log(msg);
    });

    // Create JobLogger with dual output (file + GUI)
    let logger = match JobLogger::new(&job_name, &logs_dir, log_config, Some(gui_callback)) {
        Ok(l) => Arc::new(l),
        Err(e) => {
            bridge_log(&format!("[ERROR] Failed to create job logger: {}", e));
            // Fallback to direct logging
            return run_analysis_fallback(&paths, &settings);
        }
    };

    logger.phase("Starting Analysis");
    set_progress(0, "Initializing...");

    logger.info(&format!("Job: {}", job_name));
    logger.info(&format!("Log file: {}", logger.log_path().display()));
    logger.info(&format!("Reference: {}", reference.display()));

    let mut results = Vec::new();

    // Analyze each non-reference source
    for (i, source) in paths.iter().skip(1).enumerate() {
        let source_idx = i + 2; // Source 2, 3, etc.
        let source_name = format!("Source {}", source_idx);

        logger.section(&format!("Analyzing {}", source_name));
        logger.info(&format!("Path: {}", source.display()));

        let progress_pct = ((i as f32 / (paths.len() - 1) as f32) * 100.0) as u32;
        logger.progress(progress_pct);
        set_progress(progress_pct as i32, &format!("Analyzing {}...", source_name));

        // Create analyzer with settings and attach logger for detailed output
        let analyzer = Analyzer::from_settings(&settings.analysis)
            .with_logger(Arc::clone(&logger));

        // Run analysis
        match analyzer.analyze(reference, source, &source_name) {
            Ok(result) => {
                let delay_ms = result.delay.delay_ms_raw;
                let confidence = result.avg_match_pct / 100.0; // Convert to 0-1 range

                logger.success(&format!(
                    "{} delay: {:.1}ms (match: {:.1}%, {} chunks)",
                    source_name,
                    delay_ms,
                    result.avg_match_pct,
                    result.accepted_chunks
                ));

                results.push(ffi::AnalysisResult {
                    source_index: source_idx as i32,
                    delay_ms,
                    confidence,
                    success: true,
                    error_message: String::new(),
                });
            }
            Err(e) => {
                logger.error(&format!("{} analysis failed: {}", source_name, e));
                logger.show_tail("error");

                results.push(ffi::AnalysisResult {
                    source_index: source_idx as i32,
                    delay_ms: 0.0,
                    confidence: 0.0,
                    success: false,
                    error_message: e.to_string(),
                });
            }
        }
    }

    logger.progress(100);
    set_progress(100, "Analysis complete");
    logger.phase("Analysis Complete");
    logger.flush();

    results
}

/// Fallback analysis without JobLogger (in case of logger creation failure)
fn run_analysis_fallback(paths: &[PathBuf], settings: &vsg_core::config::Settings) -> Vec<ffi::AnalysisResult> {
    let reference = &paths[0];
    let mut results = Vec::new();

    bridge_log("=== Starting Analysis (fallback mode) ===");
    bridge_log(&format!("Reference: {}", reference.display()));

    for (i, source) in paths.iter().skip(1).enumerate() {
        let source_idx = i + 2;
        let source_name = format!("Source {}", source_idx);
        bridge_log(&format!("--- Analyzing {} ---", source_name));

        let analyzer = Analyzer::from_settings(&settings.analysis);

        match analyzer.analyze(reference, source, &source_name) {
            Ok(result) => {
                let delay_ms = result.delay.delay_ms_raw;
                let confidence = result.avg_match_pct / 100.0;

                bridge_log(&format!(
                    "[SUCCESS] {} delay: {:.1}ms (match: {:.1}%)",
                    source_name, delay_ms, result.avg_match_pct
                ));

                results.push(ffi::AnalysisResult {
                    source_index: source_idx as i32,
                    delay_ms,
                    confidence,
                    success: true,
                    error_message: String::new(),
                });
            }
            Err(e) => {
                bridge_log(&format!("[ERROR] {} analysis failed: {}", source_name, e));

                results.push(ffi::AnalysisResult {
                    source_index: source_idx as i32,
                    delay_ms: 0.0,
                    confidence: 0.0,
                    success: false,
                    error_message: e.to_string(),
                });
            }
        }
    }

    bridge_log("=== Analysis Complete ===");
    results
}

fn bridge_discover_jobs(paths: &[String]) -> Vec<ffi::DiscoveredJob> {
    use std::collections::HashMap;
    use vsg_core::jobs::discover_jobs;

    // Build sources map: paths[0] = "Source 1", paths[1] = "Source 2", etc.
    let mut sources: HashMap<String, PathBuf> = HashMap::new();
    for (i, path) in paths.iter().enumerate() {
        if !path.is_empty() {
            let source_key = format!("Source {}", i + 1);
            sources.insert(source_key, PathBuf::from(path));
        }
    }

    // If no valid sources, return empty
    if sources.is_empty() {
        return vec![];
    }

    // Call vsg_core discovery
    match discover_jobs(&sources) {
        Ok(jobs) => {
            jobs.into_iter()
                .map(|job| {
                    // Convert sources map to ordered path list
                    let mut source_paths: Vec<String> = Vec::new();
                    for i in 1..=4 {
                        let key = format!("Source {}", i);
                        if let Some(path) = job.sources.get(&key) {
                            source_paths.push(path.to_string_lossy().to_string());
                        }
                    }
                    ffi::DiscoveredJob {
                        name: job.name,
                        source_paths,
                    }
                })
                .collect()
        }
        Err(e) => {
            bridge_log(&format!("[ERROR] Job discovery failed: {}", e));
            // Fallback: create single job with all paths combined
            let name = paths.first()
                .map(|p| PathBuf::from(p)
                    .file_stem()
                    .map(|s| s.to_string_lossy().to_string())
                    .unwrap_or_else(|| "Unknown".to_string()))
                .unwrap_or_else(|| "Unknown".to_string());
            vec![ffi::DiscoveredJob {
                name,
                source_paths: paths.to_vec(),
            }]
        }
    }
}

fn bridge_scan_file(path: &str) -> ffi::MediaFileInfo {
    use std::process::Command;
    use serde::Deserialize;

    #[derive(Deserialize)]
    struct MkvmergeInfo {
        container: Option<MkvContainer>,
        tracks: Vec<MkvTrack>,
        attachments: Option<Vec<MkvAttachment>>,
    }

    #[derive(Deserialize)]
    struct MkvContainer {
        properties: Option<MkvContainerProps>,
    }

    #[derive(Deserialize)]
    struct MkvContainerProps {
        duration: Option<i64>,
    }

    #[derive(Deserialize)]
    struct MkvTrack {
        id: i64,
        #[serde(rename = "type")]
        track_type: String,
        codec: Option<String>,
        properties: MkvTrackProps,
    }

    #[derive(Deserialize)]
    struct MkvTrackProps {
        language: Option<String>,
        track_name: Option<String>,
        codec_id: Option<String>,
        #[serde(default)]
        default_track: bool,
        #[serde(default)]
        forced_track: bool,
        // Audio
        audio_channels: Option<i32>,
        audio_sampling_frequency: Option<i32>,
        // Video
        pixel_dimensions: Option<String>,
    }

    #[derive(Deserialize)]
    struct MkvAttachment {
        id: i64,
        file_name: Option<String>,
        content_type: Option<String>,
        size: Option<i64>,
    }

    let path_buf = PathBuf::from(path);

    // Check file exists
    if !path_buf.exists() {
        return ffi::MediaFileInfo {
            path: path.to_string(),
            tracks: vec![],
            attachments: vec![],
            duration_ms: 0,
            success: false,
            error_message: format!("File not found: {}", path),
        };
    }

    // Run mkvmerge -J
    let output = match Command::new("mkvmerge").arg("-J").arg(path).output() {
        Ok(o) => o,
        Err(e) => {
            return ffi::MediaFileInfo {
                path: path.to_string(),
                tracks: vec![],
                attachments: vec![],
                duration_ms: 0,
                success: false,
                error_message: format!("Failed to run mkvmerge: {}", e),
            };
        }
    };

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return ffi::MediaFileInfo {
            path: path.to_string(),
            tracks: vec![],
            attachments: vec![],
            duration_ms: 0,
            success: false,
            error_message: format!("mkvmerge failed: {}", stderr),
        };
    }

    // Parse JSON
    let json_str = String::from_utf8_lossy(&output.stdout);
    let info: MkvmergeInfo = match serde_json::from_str(&json_str) {
        Ok(i) => i,
        Err(e) => {
            return ffi::MediaFileInfo {
                path: path.to_string(),
                tracks: vec![],
                attachments: vec![],
                duration_ms: 0,
                success: false,
                error_message: format!("Failed to parse mkvmerge output: {}", e),
            };
        }
    };

    // Extract duration
    let duration_ms = info.container
        .and_then(|c| c.properties)
        .and_then(|p| p.duration)
        .map(|d| d / 1_000_000) // nanoseconds to milliseconds
        .unwrap_or(0);

    // Convert tracks
    let tracks: Vec<ffi::TrackInfo> = info.tracks.into_iter().map(|t| {
        // Parse video dimensions
        let (width, height) = t.properties.pixel_dimensions
            .as_ref()
            .and_then(|dims| {
                let parts: Vec<&str> = dims.split('x').collect();
                if parts.len() == 2 {
                    Some((
                        parts[0].parse().unwrap_or(0),
                        parts[1].parse().unwrap_or(0),
                    ))
                } else {
                    None
                }
            })
            .unwrap_or((0, 0));

        ffi::TrackInfo {
            id: t.id as i32,
            track_type: t.track_type,
            codec_id: t.properties.codec_id.unwrap_or_else(|| t.codec.unwrap_or_default()),
            language: t.properties.language.unwrap_or_else(|| "und".to_string()),
            name: t.properties.track_name.unwrap_or_default(),
            is_default: t.properties.default_track,
            is_forced: t.properties.forced_track,
            channels: t.properties.audio_channels.unwrap_or(0),
            sample_rate: t.properties.audio_sampling_frequency.unwrap_or(0),
            width,
            height,
        }
    }).collect();

    // Convert attachments
    let attachments: Vec<ffi::AttachmentInfo> = info.attachments
        .unwrap_or_default()
        .into_iter()
        .map(|a| ffi::AttachmentInfo {
            id: a.id as i32,
            file_name: a.file_name.unwrap_or_default(),
            mime_type: a.content_type.unwrap_or_default(),
            size: a.size.unwrap_or(0),
        })
        .collect();

    ffi::MediaFileInfo {
        path: path.to_string(),
        tracks,
        attachments,
        duration_ms,
        success: true,
        error_message: String::new(),
    }
}

// =============================================================================
// Job Execution Implementation
// =============================================================================

fn bridge_run_job(input: &ffi::JobInput) -> ffi::JobResult {
    use std::collections::HashMap;
    use vsg_core::models::JobSpec;
    use vsg_core::orchestrator::{Context, JobState, Pipeline};
    use vsg_core::orchestrator::steps::{AnalyzeStep, ExtractStep, MuxStep};
    use vsg_core::logging::LogConfig;

    // Load settings
    let mut config_manager = get_config_manager();
    let settings = if config_manager.load_or_create().is_ok() {
        config_manager.settings().clone()
    } else {
        vsg_core::config::Settings::default()
    };

    // Validate inputs
    if input.source_paths.is_empty() {
        return ffi::JobResult {
            success: false,
            output_path: String::new(),
            steps_completed: vec![],
            steps_skipped: vec![],
            error_message: "No source paths provided".to_string(),
        };
    }

    // Build sources map
    let mut sources: HashMap<String, PathBuf> = HashMap::new();
    for (i, path_str) in input.source_paths.iter().enumerate() {
        if !path_str.is_empty() {
            let source_key = format!("Source {}", i + 1);
            sources.insert(source_key, PathBuf::from(path_str));
        }
    }

    // Validate Source 1 exists
    let source1 = match sources.get("Source 1") {
        Some(p) => p,
        None => {
            return ffi::JobResult {
                success: false,
                output_path: String::new(),
                steps_completed: vec![],
                steps_skipped: vec![],
                error_message: "Source 1 is required".to_string(),
            };
        }
    };

    if !source1.exists() {
        return ffi::JobResult {
            success: false,
            output_path: String::new(),
            steps_completed: vec![],
            steps_skipped: vec![],
            error_message: format!("Source 1 not found: {}", source1.display()),
        };
    }

    // Create JobSpec
    let mut job_spec = JobSpec::new(sources.clone());

    // Parse layout JSON if provided
    if !input.layout_json.is_empty() {
        match serde_json::from_str::<Vec<HashMap<String, serde_json::Value>>>(&input.layout_json) {
            Ok(layout) => {
                job_spec.manual_layout = Some(layout);
            }
            Err(e) => {
                bridge_log(&format!("[WARNING] Failed to parse layout JSON: {}", e));
                // Continue without layout - will use auto-generated layout later
            }
        }
    }

    // Set up directories
    let output_dir = PathBuf::from(&settings.paths.output_folder);
    let work_dir = PathBuf::from(&settings.paths.temp_root).join(&input.job_id);
    let logs_dir = PathBuf::from(&settings.paths.logs_folder);

    // Create directories
    for dir in [&output_dir, &work_dir, &logs_dir] {
        if let Err(e) = std::fs::create_dir_all(dir) {
            return ffi::JobResult {
                success: false,
                output_path: String::new(),
                steps_completed: vec![],
                steps_skipped: vec![],
                error_message: format!("Failed to create directory {}: {}", dir.display(), e),
            };
        }
    }

    // Create LogConfig from settings
    let log_config = LogConfig {
        compact: settings.logging.compact,
        progress_step: settings.logging.progress_step,
        error_tail: settings.logging.error_tail as usize,
        ..LogConfig::default()
    };

    // Create GUI callback
    let gui_callback: Box<dyn Fn(&str) + Send + Sync> = Box::new(|msg: &str| {
        bridge_log(msg);
    });

    // Create JobLogger
    let logger = match JobLogger::new(&input.job_name, &logs_dir, log_config, Some(gui_callback)) {
        Ok(l) => Arc::new(l),
        Err(e) => {
            return ffi::JobResult {
                success: false,
                output_path: String::new(),
                steps_completed: vec![],
                steps_skipped: vec![],
                error_message: format!("Failed to create logger: {}", e),
            };
        }
    };

    logger.phase("Starting Job");
    logger.info(&format!("Job ID: {}", input.job_id));
    logger.info(&format!("Job Name: {}", input.job_name));
    logger.info(&format!("Sources: {}", sources.len()));
    for (key, path) in &sources {
        logger.info(&format!("  {}: {}", key, path.display()));
    }

    set_progress(0, "Initializing...");

    // Create Context
    let ctx = Context::new(
        job_spec,
        settings.clone(),
        &input.job_name,
        work_dir,
        output_dir.clone(),
        Arc::clone(&logger),
    ).with_progress_callback(Box::new(|step, pct, msg| {
        set_progress(pct as i32, &format!("{}: {}", step, msg));
    }));

    // Create JobState
    let mut state = JobState::new(&input.job_id);

    // Build pipeline
    let mut pipeline = Pipeline::new();

    // Add Extract step (reads container info for delays)
    pipeline.add_step(ExtractStep::new());

    // Add Analyze step (if multiple sources)
    if sources.len() > 1 {
        pipeline.add_step(AnalyzeStep::new());
    }

    // Add Mux step
    pipeline.add_step(MuxStep::new());

    logger.info(&format!("Pipeline steps: {:?}", pipeline.step_names()));

    // Run pipeline
    match pipeline.run(&ctx, &mut state) {
        Ok(result) => {
            let output_path = state.mux
                .as_ref()
                .map(|m| m.output_path.to_string_lossy().to_string())
                .unwrap_or_default();

            logger.phase("Job Complete");
            logger.success(&format!("Output: {}", output_path));
            logger.flush();

            set_progress(100, "Complete");

            ffi::JobResult {
                success: true,
                output_path,
                steps_completed: result.steps_completed,
                steps_skipped: result.steps_skipped,
                error_message: String::new(),
            }
        }
        Err(e) => {
            logger.error(&format!("Job failed: {}", e));
            logger.show_tail("error");
            logger.flush();

            set_progress(0, "Failed");

            ffi::JobResult {
                success: false,
                output_path: String::new(),
                steps_completed: vec![],
                steps_skipped: vec![],
                error_message: e.to_string(),
            }
        }
    }
}

/// Clean up temporary files from a work directory.
fn bridge_cleanup_temp(work_dir: &str) -> bool {
    let path = PathBuf::from(work_dir);

    if !path.exists() {
        return true; // Nothing to clean
    }

    match std::fs::remove_dir_all(&path) {
        Ok(_) => {
            bridge_log(&format!("Cleaned up temp directory: {}", work_dir));
            true
        }
        Err(e) => {
            bridge_log(&format!("[WARNING] Failed to clean temp directory {}: {}", work_dir, e));
            false
        }
    }
}

fn default_app_settings() -> ffi::AppSettings {
    ffi::AppSettings {
        paths: ffi::PathSettings {
            output_folder: "sync_output".to_string(),
            temp_root: ".temp".to_string(),
            logs_folder: ".logs".to_string(),
            last_source1_path: String::new(),
            last_source2_path: String::new(),
        },
        logging: ffi::LoggingSettings {
            compact: true,
            autoscroll: true,
            error_tail: 20,
            progress_step: 20,
            show_options_pretty: false,
            show_options_json: false,
            archive_logs: true,
        },
        analysis: ffi::AnalysisSettings {
            mode: "audio".to_string(),
            correlation_method: "scc".to_string(),
            chunk_count: 10,
            chunk_duration: 15,
            min_match_pct: 5.0,
            scan_start_pct: 5.0,
            scan_end_pct: 95.0,
            use_soxr: true,
            audio_peak_fit: true,
            sync_mode: "positive_only".to_string(),
        },
        chapters: ffi::ChapterSettings {
            rename: false,
            snap_enabled: false,
            snap_mode: "previous".to_string(),
            snap_threshold_ms: 250,
            snap_starts_only: true,
        },
        postprocess: ffi::PostProcessSettings {
            disable_track_stats_tags: false,
            disable_header_compression: true,
            apply_dialog_norm: false,
        },
    }
}
