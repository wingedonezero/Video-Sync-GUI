//! Settings handlers.

use vsg_core::models::{
    AnalysisMode, CorrelationMethod, DelaySelectionMode, FilteringMethod, SnapMode, SyncMode,
};

use crate::app::{App, SettingKey, SettingValue};

impl App {
    /// Handle setting changed.
    pub fn handle_setting_changed(&mut self, key: SettingKey, value: SettingValue) {
        let Some(settings) = &mut self.pending_settings else {
            return;
        };

        match (key, value) {
            // Paths
            (SettingKey::OutputFolder, SettingValue::String(v)) => settings.paths.output_folder = v,
            (SettingKey::TempRoot, SettingValue::String(v)) => settings.paths.temp_root = v,
            (SettingKey::LogsFolder, SettingValue::String(v)) => settings.paths.logs_folder = v,

            // Logging
            (SettingKey::CompactLogging, SettingValue::Bool(v)) => settings.logging.compact = v,
            (SettingKey::Autoscroll, SettingValue::Bool(v)) => settings.logging.autoscroll = v,
            (SettingKey::ErrorTail, SettingValue::I32(v)) => settings.logging.error_tail = v as u32,
            (SettingKey::ProgressStep, SettingValue::I32(v)) => {
                settings.logging.progress_step = v as u32
            }
            (SettingKey::ShowOptionsPretty, SettingValue::Bool(v)) => {
                settings.logging.show_options_pretty = v
            }
            (SettingKey::ShowOptionsJson, SettingValue::Bool(v)) => {
                settings.logging.show_options_json = v
            }

            // Analysis
            (SettingKey::AnalysisMode, SettingValue::I32(v)) => {
                settings.analysis.mode = match v {
                    0 => AnalysisMode::AudioCorrelation,
                    _ => AnalysisMode::VideoDiff,
                };
            }
            (SettingKey::CorrelationMethod, SettingValue::I32(v)) => {
                settings.analysis.correlation_method = match v {
                    0 => CorrelationMethod::Scc,
                    1 => CorrelationMethod::GccPhat,
                    2 => CorrelationMethod::GccScot,
                    _ => CorrelationMethod::Whitened,
                };
            }
            (SettingKey::SyncMode, SettingValue::I32(v)) => {
                settings.analysis.sync_mode = match v {
                    0 => SyncMode::PositiveOnly,
                    _ => SyncMode::AllowNegative,
                };
            }
            (SettingKey::LangSource1, SettingValue::String(v)) => {
                settings.analysis.lang_source1 = if v.is_empty() { None } else { Some(v) };
            }
            (SettingKey::LangOthers, SettingValue::String(v)) => {
                settings.analysis.lang_others = if v.is_empty() { None } else { Some(v) };
            }
            (SettingKey::ChunkCount, SettingValue::I32(v)) => {
                settings.analysis.chunk_count = v as u32
            }
            (SettingKey::ChunkDuration, SettingValue::I32(v)) => {
                settings.analysis.chunk_duration = v as u32
            }
            (SettingKey::MinMatchPct, SettingValue::F32(v)) => {
                settings.analysis.min_match_pct = v as f64
            }
            (SettingKey::ScanStartPct, SettingValue::F32(v)) => {
                settings.analysis.scan_start_pct = v as f64
            }
            (SettingKey::ScanEndPct, SettingValue::F32(v)) => {
                settings.analysis.scan_end_pct = v as f64
            }
            (SettingKey::FilteringMethod, SettingValue::I32(v)) => {
                settings.analysis.filtering_method = match v {
                    0 => FilteringMethod::None,
                    1 => FilteringMethod::LowPass,
                    2 => FilteringMethod::BandPass,
                    _ => FilteringMethod::HighPass,
                };
            }
            (SettingKey::FilterLowCutoffHz, SettingValue::I32(v)) => {
                settings.analysis.filter_low_cutoff_hz = v as f64
            }
            (SettingKey::FilterHighCutoffHz, SettingValue::I32(v)) => {
                settings.analysis.filter_high_cutoff_hz = v as f64
            }
            (SettingKey::UseSoxr, SettingValue::Bool(v)) => settings.analysis.use_soxr = v,
            (SettingKey::AudioPeakFit, SettingValue::Bool(v)) => settings.analysis.audio_peak_fit = v,
            (SettingKey::MultiCorrelationEnabled, SettingValue::Bool(v)) => {
                settings.analysis.multi_correlation_enabled = v
            }
            (SettingKey::MultiCorrScc, SettingValue::Bool(v)) => settings.analysis.multi_corr_scc = v,
            (SettingKey::MultiCorrGccPhat, SettingValue::Bool(v)) => {
                settings.analysis.multi_corr_gcc_phat = v
            }
            (SettingKey::MultiCorrGccScot, SettingValue::Bool(v)) => {
                settings.analysis.multi_corr_gcc_scot = v
            }
            (SettingKey::MultiCorrWhitened, SettingValue::Bool(v)) => {
                settings.analysis.multi_corr_whitened = v
            }

            // Delay selection
            (SettingKey::DelaySelectionMode, SettingValue::I32(v)) => {
                settings.analysis.delay_selection_mode = match v {
                    0 => DelaySelectionMode::Mode,
                    1 => DelaySelectionMode::ModeClustered,
                    2 => DelaySelectionMode::ModeEarly,
                    3 => DelaySelectionMode::FirstStable,
                    _ => DelaySelectionMode::Average,
                };
            }
            (SettingKey::MinAcceptedChunks, SettingValue::I32(v)) => {
                settings.analysis.min_accepted_chunks = v as u32
            }
            (SettingKey::FirstStableMinChunks, SettingValue::I32(v)) => {
                settings.analysis.first_stable_min_chunks = v as u32
            }
            (SettingKey::FirstStableSkipUnstable, SettingValue::Bool(v)) => {
                settings.analysis.first_stable_skip_unstable = v
            }
            (SettingKey::EarlyClusterWindow, SettingValue::I32(v)) => {
                settings.analysis.early_cluster_window = v as u32
            }
            (SettingKey::EarlyClusterThreshold, SettingValue::I32(v)) => {
                settings.analysis.early_cluster_threshold = v as u32
            }

            // Chapters
            (SettingKey::ChapterRename, SettingValue::Bool(v)) => settings.chapters.rename = v,
            (SettingKey::ChapterSnap, SettingValue::Bool(v)) => settings.chapters.snap_enabled = v,
            (SettingKey::SnapMode, SettingValue::I32(v)) => {
                settings.chapters.snap_mode = match v {
                    0 => SnapMode::Previous,
                    _ => SnapMode::Nearest,
                };
            }
            (SettingKey::SnapThresholdMs, SettingValue::I32(v)) => {
                settings.chapters.snap_threshold_ms = v as u32
            }
            (SettingKey::SnapStartsOnly, SettingValue::Bool(v)) => {
                settings.chapters.snap_starts_only = v
            }

            // Post-process
            (SettingKey::DisableTrackStats, SettingValue::Bool(v)) => {
                settings.postprocess.disable_track_stats_tags = v
            }
            (SettingKey::DisableHeaderCompression, SettingValue::Bool(v)) => {
                settings.postprocess.disable_header_compression = v
            }
            (SettingKey::ApplyDialogNorm, SettingValue::Bool(v)) => {
                settings.postprocess.apply_dialog_norm = v
            }

            _ => {}
        }
    }

    /// Save settings to disk.
    pub fn save_settings(&mut self) {
        if let Some(pending) = self.pending_settings.take() {
            let result = {
                let mut cfg = self.config.lock().unwrap();
                *cfg.settings_mut() = pending;
                cfg.save()
            };
            if let Err(e) = result {
                self.append_log(&format!("Failed to save settings: {}", e));
            } else {
                self.append_log("Settings saved.");
            }
        }
    }
}
