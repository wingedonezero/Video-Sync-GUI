//! CXX Bridge between vsg_core (Rust) and Qt UI (C++)
//!
//! This crate provides safe FFI bindings using the CXX library.
//! All vsg_core functionality is exposed through this bridge.

use std::collections::VecDeque;
use std::path::PathBuf;
use std::sync::Mutex;

use vsg_core::analysis::Analyzer;
use vsg_core::config::{ConfigManager, ConfigSection};

// Global message queue for logging from Rust to C++
static LOG_QUEUE: Mutex<VecDeque<String>> = Mutex::new(VecDeque::new());
static PROGRESS: Mutex<(i32, String)> = Mutex::new((0, String::new()));

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

    /// A discovered job from paths
    #[derive(Debug, Clone)]
    struct DiscoveredJob {
        name: String,
        source_paths: Vec<String>,
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

        /// Get vsg_core version string
        fn bridge_version() -> String;

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

    bridge_log("=== Starting Analysis ===");
    set_progress(0, "Initializing...");

    // Convert paths
    let paths: Vec<PathBuf> = source_paths.iter().map(PathBuf::from).collect();
    let reference = &paths[0];

    bridge_log(&format!("Reference: {}", reference.display()));

    let mut results = Vec::new();

    // Analyze each non-reference source
    for (i, source) in paths.iter().skip(1).enumerate() {
        let source_idx = i + 2; // Source 2, 3, etc.
        bridge_log(&format!("--- Analyzing Source {} ---", source_idx));
        bridge_log(&format!("Path: {}", source.display()));

        set_progress(
            ((i as f32 / (paths.len() - 1) as f32) * 100.0) as i32,
            &format!("Analyzing Source {}...", source_idx),
        );

        // Create analyzer with settings
        let analyzer = Analyzer::new(&settings.analysis);

        // Run analysis
        match analyzer.analyze(reference, source) {
            Ok(delay_result) => {
                let delay_ms = delay_result.delay.as_millis_f64();
                let confidence = delay_result.confidence;

                bridge_log(&format!(
                    "[SUCCESS] Source {} delay: {:.1}ms (confidence: {:.1}%)",
                    source_idx,
                    delay_ms,
                    confidence * 100.0
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
                bridge_log(&format!("[ERROR] Source {} analysis failed: {}", source_idx, e));

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

    set_progress(100, "Analysis complete");
    bridge_log("=== Analysis Complete ===");

    results
}

fn bridge_discover_jobs(paths: &[String]) -> Vec<ffi::DiscoveredJob> {
    // TODO: Wire up to vsg_core job discovery
    // For now, return stub
    paths
        .iter()
        .map(|p| ffi::DiscoveredJob {
            name: PathBuf::from(p)
                .file_stem()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_else(|| "Unknown".to_string()),
            source_paths: vec![p.clone()],
        })
        .collect()
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
