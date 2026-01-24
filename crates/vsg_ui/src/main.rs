//! Video Sync GUI - Main entry point

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use vsg_core::config::{ConfigManager, Settings};

// Include the Slint-generated code
slint::include_modules!();

/// Default config path
fn default_config_path() -> PathBuf {
    dirs::config_dir()
        .unwrap_or_else(|| PathBuf::from("."))
        .join("video-sync-gui")
        .join("settings.toml")
}

fn main() -> Result<(), slint::PlatformError> {
    // Load configuration
    let config_path = default_config_path();
    let mut config_manager = ConfigManager::new(&config_path);

    if let Err(e) = config_manager.load_or_create() {
        eprintln!("Warning: Failed to load config: {}. Using defaults.", e);
    }

    // Wrap config in Arc<Mutex> for sharing between callbacks
    let config = Arc::new(Mutex::new(config_manager));

    // Create the main window
    let main_window = MainWindow::new()?;

    // Log that we're starting
    let version_info = format!(
        "Video Sync GUI started.\nCore version: {}\nConfig: {}\n",
        vsg_core::version(),
        config_path.display()
    );
    main_window.set_log_text(version_info.into());

    // Set archive_logs from config
    {
        let cfg = config.lock().unwrap();
        main_window.set_archive_logs(cfg.settings().logging.archive_logs);
    }

    // Settings button
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
                            } else {
                                if let Some(w) = window_for_save.upgrade() {
                                    append_log(&w, "Settings saved.");
                                }
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

    // Queue Jobs button
    let window_weak = main_window.as_weak();
    main_window.on_queue_jobs_clicked(move || {
        if let Some(window) = window_weak.upgrade() {
            append_log(&window, "Opening job queue...");
            append_log(&window, "Job queue dialog not yet implemented");
        }
    });

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

    // Handle source path changes (from drag-drop or manual edit)
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

    // Analyze Only button
    let window_weak = main_window.as_weak();
    main_window.on_analyze_only_clicked(move || {
        if let Some(window) = window_weak.upgrade() {
            let source1 = window.get_source1_path();
            let source2 = window.get_source2_path();

            if source1.is_empty() || source2.is_empty() {
                append_log(&window, "[WARNING] Please select at least Source 1 and Source 2");
                return;
            }

            window.set_status_text("Analyzing...".into());
            window.set_progress_value(0.0);

            append_log(&window, "=== Starting Analysis ===");
            append_log(&window, &format!("Source 1: {}", source1));
            append_log(&window, &format!("Source 2: {}", source2));

            let source3 = window.get_source3_path();
            if !source3.is_empty() {
                append_log(&window, &format!("Source 3: {}", source3));
            }

            // Simulate progress
            window.set_progress_value(50.0);
            append_log(&window, "Analysis step not yet implemented - using stub");

            // Show stub results
            window.set_delay_source2("0 ms".into());
            if !source3.is_empty() {
                window.set_delay_source3("0 ms".into());
            }

            window.set_progress_value(100.0);
            window.set_status_text("Ready".into());
            append_log(&window, "=== Analysis Complete ===");
        }
    });

    // Run the event loop
    main_window.run()
}

/// Helper to append text to the log
fn append_log(window: &MainWindow, message: &str) {
    let current = window.get_log_text();
    let new_text = format!("{}{}\n", current, message);
    window.set_log_text(new_text.into());
}

/// Open a file dialog to pick a video file
fn pick_video_file(title: &str) -> Option<PathBuf> {
    rfd::FileDialog::new()
        .set_title(title)
        .add_filter("Video Files", &["mkv", "mp4", "avi", "mov", "webm", "m4v", "ts", "m2ts"])
        .add_filter("All Files", &["*"])
        .pick_file()
}

/// Clean up a file URL (from drag-drop) to a regular path
/// Handles file:// URLs and URL-encoded characters
fn clean_file_url(url: &str) -> String {
    let path = if url.starts_with("file://") {
        // Remove file:// prefix
        let without_prefix = &url[7..];
        // URL decode (handle %20 for spaces, etc.)
        percent_decode(without_prefix)
    } else {
        url.to_string()
    };

    // Trim any trailing whitespace/newlines
    path.trim().to_string()
}

/// Simple percent decoding for file paths
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

/// Populate settings window with values from config
fn populate_settings_window(settings: &SettingsWindow, cfg: &Settings) {
    // Storage tab
    settings.set_output_folder(cfg.paths.output_folder.clone().into());
    settings.set_temp_root(cfg.paths.temp_root.clone().into());
    settings.set_logs_folder(cfg.paths.logs_folder.clone().into());

    // Logging tab
    settings.set_compact_logging(cfg.logging.compact);
    settings.set_autoscroll(cfg.logging.autoscroll);
    settings.set_error_tail(cfg.logging.error_tail as i32);
    settings.set_progress_step(cfg.logging.progress_step as i32);
    settings.set_show_options_pretty(cfg.logging.show_options_pretty);
    settings.set_show_options_json(cfg.logging.show_options_json);

    // Analysis tab
    settings.set_analysis_mode_index(match cfg.analysis.mode {
        vsg_core::models::AnalysisMode::AudioCorrelation => 0,
        vsg_core::models::AnalysisMode::VideoDiff => 1,
    });
    settings.set_lang_source1(cfg.analysis.lang_source1.clone().unwrap_or_default().into());
    settings.set_lang_others(cfg.analysis.lang_others.clone().unwrap_or_default().into());
    settings.set_chunk_count(cfg.analysis.chunk_count as i32);
    settings.set_chunk_duration(cfg.analysis.chunk_duration as i32);
    settings.set_min_match_pct(cfg.analysis.min_match_pct as f32);
    settings.set_scan_start_pct(cfg.analysis.scan_start_pct as f32);
    settings.set_scan_end_pct(cfg.analysis.scan_end_pct as f32);

    // Chapters tab
    settings.set_chapter_rename(cfg.chapters.rename);
    settings.set_chapter_snap(cfg.chapters.snap_enabled);
    settings.set_snap_mode_index(match cfg.chapters.snap_mode {
        vsg_core::models::SnapMode::Previous => 0,
        vsg_core::models::SnapMode::Nearest => 1,
    });
    settings.set_snap_threshold_ms(cfg.chapters.snap_threshold_ms as i32);
    settings.set_snap_starts_only(cfg.chapters.snap_starts_only);

    // Merge Behavior tab
    settings.set_disable_track_stats(cfg.postprocess.disable_track_stats_tags);
    settings.set_disable_header_compression(cfg.postprocess.disable_header_compression);
    settings.set_apply_dialog_norm(cfg.postprocess.apply_dialog_norm);
}

/// Read values from settings window back into config
fn read_settings_from_window(settings: &SettingsWindow, cfg: &mut Settings) {
    // Storage tab
    cfg.paths.output_folder = settings.get_output_folder().to_string();
    cfg.paths.temp_root = settings.get_temp_root().to_string();
    cfg.paths.logs_folder = settings.get_logs_folder().to_string();

    // Logging tab
    cfg.logging.compact = settings.get_compact_logging();
    cfg.logging.autoscroll = settings.get_autoscroll();
    cfg.logging.error_tail = settings.get_error_tail() as u32;
    cfg.logging.progress_step = settings.get_progress_step() as u32;
    cfg.logging.show_options_pretty = settings.get_show_options_pretty();
    cfg.logging.show_options_json = settings.get_show_options_json();

    // Analysis tab
    cfg.analysis.mode = match settings.get_analysis_mode_index() {
        0 => vsg_core::models::AnalysisMode::AudioCorrelation,
        _ => vsg_core::models::AnalysisMode::VideoDiff,
    };
    let lang1 = settings.get_lang_source1().to_string();
    cfg.analysis.lang_source1 = if lang1.is_empty() { None } else { Some(lang1) };
    let lang_others = settings.get_lang_others().to_string();
    cfg.analysis.lang_others = if lang_others.is_empty() { None } else { Some(lang_others) };
    cfg.analysis.chunk_count = settings.get_chunk_count() as u32;
    cfg.analysis.chunk_duration = settings.get_chunk_duration() as u32;
    cfg.analysis.min_match_pct = settings.get_min_match_pct() as f64;
    cfg.analysis.scan_start_pct = settings.get_scan_start_pct() as f64;
    cfg.analysis.scan_end_pct = settings.get_scan_end_pct() as f64;

    // Chapters tab
    cfg.chapters.rename = settings.get_chapter_rename();
    cfg.chapters.snap_enabled = settings.get_chapter_snap();
    cfg.chapters.snap_mode = match settings.get_snap_mode_index() {
        0 => vsg_core::models::SnapMode::Previous,
        _ => vsg_core::models::SnapMode::Nearest,
    };
    cfg.chapters.snap_threshold_ms = settings.get_snap_threshold_ms() as u32;
    cfg.chapters.snap_starts_only = settings.get_snap_starts_only();

    // Merge Behavior tab
    cfg.postprocess.disable_track_stats_tags = settings.get_disable_track_stats();
    cfg.postprocess.disable_header_compression = settings.get_disable_header_compression();
    cfg.postprocess.apply_dialog_norm = settings.get_apply_dialog_norm();
}
