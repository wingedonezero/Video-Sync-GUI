//! Settings window logic.
//!
//! This module contains functions for populating and reading
//! values from the settings window UI.

use std::path::PathBuf;

use slint::ComponentHandle;
use vsg_core::config::Settings;
use vsg_core::models::{AnalysisMode, FilteringMethod, SnapMode};

use crate::ui::SettingsWindow;

/// Populate settings window with values from config.
pub fn populate_settings_window(settings: &SettingsWindow, cfg: &Settings) {
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
        AnalysisMode::AudioCorrelation => 0,
        AnalysisMode::VideoDiff => 1,
    });
    settings.set_lang_source1(cfg.analysis.lang_source1.clone().unwrap_or_default().into());
    settings.set_lang_others(cfg.analysis.lang_others.clone().unwrap_or_default().into());
    settings.set_chunk_count(cfg.analysis.chunk_count as i32);
    settings.set_chunk_duration(cfg.analysis.chunk_duration as i32);
    settings.set_min_match_pct(cfg.analysis.min_match_pct as f32);
    settings.set_scan_start_pct(cfg.analysis.scan_start_pct as f32);
    settings.set_scan_end_pct(cfg.analysis.scan_end_pct as f32);
    settings.set_filtering_method_index(match cfg.analysis.filtering_method {
        FilteringMethod::None => 0,
        FilteringMethod::LowPass => 1,
        FilteringMethod::BandPass => 2,
        FilteringMethod::HighPass => 3,
    });
    settings.set_use_soxr(cfg.analysis.use_soxr);
    settings.set_audio_peak_fit(cfg.analysis.audio_peak_fit);

    // Chapters tab
    settings.set_chapter_rename(cfg.chapters.rename);
    settings.set_chapter_snap(cfg.chapters.snap_enabled);
    settings.set_snap_mode_index(match cfg.chapters.snap_mode {
        SnapMode::Previous => 0,
        SnapMode::Nearest => 1,
    });
    settings.set_snap_threshold_ms(cfg.chapters.snap_threshold_ms as i32);
    settings.set_snap_starts_only(cfg.chapters.snap_starts_only);

    // Merge Behavior tab
    settings.set_disable_track_stats(cfg.postprocess.disable_track_stats_tags);
    settings.set_disable_header_compression(cfg.postprocess.disable_header_compression);
    settings.set_apply_dialog_norm(cfg.postprocess.apply_dialog_norm);
}

/// Read values from settings window back into config.
pub fn read_settings_from_window(settings: &SettingsWindow, cfg: &mut Settings) {
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
        0 => AnalysisMode::AudioCorrelation,
        _ => AnalysisMode::VideoDiff,
    };
    let lang1 = settings.get_lang_source1().to_string();
    cfg.analysis.lang_source1 = if lang1.is_empty() { None } else { Some(lang1) };
    let lang_others = settings.get_lang_others().to_string();
    cfg.analysis.lang_others = if lang_others.is_empty() {
        None
    } else {
        Some(lang_others)
    };
    cfg.analysis.chunk_count = settings.get_chunk_count() as u32;
    cfg.analysis.chunk_duration = settings.get_chunk_duration() as u32;
    cfg.analysis.min_match_pct = settings.get_min_match_pct() as f64;
    cfg.analysis.scan_start_pct = settings.get_scan_start_pct() as f64;
    cfg.analysis.scan_end_pct = settings.get_scan_end_pct() as f64;
    cfg.analysis.filtering_method = match settings.get_filtering_method_index() {
        0 => FilteringMethod::None,
        1 => FilteringMethod::LowPass,
        2 => FilteringMethod::BandPass,
        _ => FilteringMethod::HighPass,
    };
    cfg.analysis.use_soxr = settings.get_use_soxr();
    cfg.analysis.audio_peak_fit = settings.get_audio_peak_fit();

    // Chapters tab
    cfg.chapters.rename = settings.get_chapter_rename();
    cfg.chapters.snap_enabled = settings.get_chapter_snap();
    cfg.chapters.snap_mode = match settings.get_snap_mode_index() {
        0 => SnapMode::Previous,
        _ => SnapMode::Nearest,
    };
    cfg.chapters.snap_threshold_ms = settings.get_snap_threshold_ms() as u32;
    cfg.chapters.snap_starts_only = settings.get_snap_starts_only();

    // Merge Behavior tab
    cfg.postprocess.disable_track_stats_tags = settings.get_disable_track_stats();
    cfg.postprocess.disable_header_compression = settings.get_disable_header_compression();
    cfg.postprocess.apply_dialog_norm = settings.get_apply_dialog_norm();
}

/// Set up browse button callbacks for the settings window.
pub fn setup_settings_browse_buttons(settings: &SettingsWindow) {
    // Browse output folder
    let settings_weak = settings.as_weak();
    settings.on_browse_output(move || {
        if let Some(s) = settings_weak.upgrade() {
            if let Some(path) = pick_folder("Select Output Directory") {
                s.set_output_folder(path.to_string_lossy().to_string().into());
            }
        }
    });

    // Browse temp folder
    let settings_weak = settings.as_weak();
    settings.on_browse_temp(move || {
        if let Some(s) = settings_weak.upgrade() {
            if let Some(path) = pick_folder("Select Temporary Directory") {
                s.set_temp_root(path.to_string_lossy().to_string().into());
            }
        }
    });

    // Browse logs folder
    let settings_weak = settings.as_weak();
    settings.on_browse_logs(move || {
        if let Some(s) = settings_weak.upgrade() {
            if let Some(path) = pick_folder("Select Logs Directory") {
                s.set_logs_folder(path.to_string_lossy().to_string().into());
            }
        }
    });
}

/// Open a folder picker dialog.
fn pick_folder(title: &str) -> Option<PathBuf> {
    rfd::FileDialog::new().set_title(title).pick_folder()
}
