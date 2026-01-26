//! Settings window view.
//!
//! Multi-tab settings dialog with all configuration options.

use iced::widget::{
    button, checkbox, column, container, pick_list, row, scrollable, text, text_input, Space,
};
use iced::{Alignment, Element, Length};

use iced_aw::{TabLabel, Tabs};

use crate::app::{App, FolderType, Message, SettingKey, SettingValue};

/// Tab identifiers
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SettingsTab {
    Storage,
    Analysis,
    DelaySelection,
    Chapters,
    MergeBehavior,
    Logging,
}

impl SettingsTab {
    fn all() -> &'static [SettingsTab] {
        &[
            SettingsTab::Storage,
            SettingsTab::Analysis,
            SettingsTab::DelaySelection,
            SettingsTab::Chapters,
            SettingsTab::MergeBehavior,
            SettingsTab::Logging,
        ]
    }

    fn label(&self) -> &'static str {
        match self {
            SettingsTab::Storage => "Storage",
            SettingsTab::Analysis => "Analysis",
            SettingsTab::DelaySelection => "Delay Selection",
            SettingsTab::Chapters => "Chapters",
            SettingsTab::MergeBehavior => "Merge Behavior",
            SettingsTab::Logging => "Logging",
        }
    }
}

/// Build the settings window view.
pub fn view(app: &App) -> Element<Message> {
    let Some(settings) = &app.pending_settings else {
        return container(text("No settings loaded"))
            .padding(20)
            .into();
    };

    let active_tab = SettingsTab::all()
        .get(app.settings_active_tab)
        .copied()
        .unwrap_or(SettingsTab::Storage);

    // Build tabs
    let tabs = Tabs::new_with_tabs(
        SettingsTab::all()
            .iter()
            .map(|tab| {
                let content: Element<Message> = match tab {
                    SettingsTab::Storage => storage_tab(settings),
                    SettingsTab::Analysis => analysis_tab(settings),
                    SettingsTab::DelaySelection => delay_selection_tab(settings),
                    SettingsTab::Chapters => chapters_tab(settings),
                    SettingsTab::MergeBehavior => merge_behavior_tab(settings),
                    SettingsTab::Logging => logging_tab(settings),
                };
                (*tab, TabLabel::Text(tab.label().to_string()), content)
            }),
        |tab| {
            Message::SettingsTabSelected(SettingsTab::all().iter().position(|t| *t == tab).unwrap_or(0))
        },
    )
    .set_active_tab(&active_tab)
    .tab_bar_position(iced_aw::TabBarPosition::Top)
    .height(Length::Fill);

    // Button row
    let button_row = row![
        Space::new().width(Length::Fill),
        button("Cancel").on_press(Message::CancelSettings),
        button("Save").on_press(Message::SaveSettings),
    ]
    .spacing(8);

    let content = column![
        text("Application Settings").size(24),
        Space::new().height(12),
        tabs,
        Space::new().height(12),
        button_row,
    ]
    .spacing(4)
    .padding(16);

    container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}

/// Storage tab
fn storage_tab(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let output_path = settings.paths.output_folder.clone();
    let temp_path = settings.paths.temp_root.clone();
    let logs_path = settings.paths.logs_folder.clone();

    let content = column![
        text("Storage Paths").size(16),
        Space::new().height(8),
        folder_row("Output Folder:", &output_path, FolderType::Output),
        folder_row("Temp Folder:", &temp_path, FolderType::Temp),
        folder_row("Logs Folder:", &logs_path, FolderType::Logs),
    ]
    .spacing(8);

    scrollable(container(content).padding(16).width(Length::Fill))
        .height(Length::Fill)
        .into()
}

fn folder_row(label: &str, path: &str, folder_type: FolderType) -> Element<'static, Message> {
    let key = match folder_type {
        FolderType::Output => SettingKey::OutputFolder,
        FolderType::Temp => SettingKey::TempRoot,
        FolderType::Logs => SettingKey::LogsFolder,
    };

    let label_owned = label.to_string();
    let path_owned = path.to_string();

    row![
        text(label_owned).width(120),
        text_input("", &path_owned)
            .on_input(move |s| Message::SettingChanged(key.clone(), SettingValue::String(s)))
            .width(Length::Fill),
        button("Browse...").on_press(Message::BrowseFolder(folder_type)),
    ]
    .spacing(8)
    .align_y(Alignment::Center)
    .into()
}

/// Analysis tab - includes multi-correlation settings
fn analysis_tab(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let analysis_mode_idx = match settings.analysis.mode {
        vsg_core::models::AnalysisMode::AudioCorrelation => 0,
        vsg_core::models::AnalysisMode::VideoDiff => 1,
    };

    let corr_method_idx = match settings.analysis.correlation_method {
        vsg_core::models::CorrelationMethod::Scc => 0,
        vsg_core::models::CorrelationMethod::GccPhat => 1,
        vsg_core::models::CorrelationMethod::GccScot => 2,
        vsg_core::models::CorrelationMethod::Whitened => 3,
    };

    let sync_mode_idx = match settings.analysis.sync_mode {
        vsg_core::models::SyncMode::PositiveOnly => 0,
        vsg_core::models::SyncMode::AllowNegative => 1,
    };

    let filtering_idx = match settings.analysis.filtering_method {
        vsg_core::models::FilteringMethod::None => 0,
        vsg_core::models::FilteringMethod::LowPass => 1,
        vsg_core::models::FilteringMethod::BandPass => 2,
        vsg_core::models::FilteringMethod::HighPass => 3,
    };

    let analysis_modes: Vec<&'static str> = vec!["Audio Correlation", "Video Diff"];
    let correlation_methods: Vec<&'static str> = vec!["SCC", "GCC-PHAT", "GCC-SCOT", "Whitened"];
    let sync_modes: Vec<&'static str> = vec!["Positive Only", "Allow Negative"];
    let filtering_methods: Vec<&'static str> = vec!["None", "Low Pass", "Band Pass", "High Pass"];

    let chunk_count_str = settings.analysis.chunk_count.to_string();
    let chunk_duration_str = settings.analysis.chunk_duration.to_string();
    let min_match_str = format!("{:.1}", settings.analysis.min_match_pct);
    let scan_start_str = format!("{:.1}", settings.analysis.scan_start_pct);
    let scan_end_str = format!("{:.1}", settings.analysis.scan_end_pct);
    let filter_low_str = format!("{:.0}", settings.analysis.filter_low_cutoff_hz);
    let filter_high_str = format!("{:.0}", settings.analysis.filter_high_cutoff_hz);
    let lang_source1 = settings.analysis.lang_source1.clone().unwrap_or_default();
    let lang_others = settings.analysis.lang_others.clone().unwrap_or_default();

    let audio_peak_fit = settings.analysis.audio_peak_fit;
    let use_soxr = settings.analysis.use_soxr;

    // Multi-correlation settings
    let multi_corr_enabled = settings.analysis.multi_correlation_enabled;
    let scc = settings.analysis.multi_corr_scc;
    let gcc_phat = settings.analysis.multi_corr_gcc_phat;
    let gcc_scot = settings.analysis.multi_corr_gcc_scot;
    let whitened = settings.analysis.multi_corr_whitened;

    let content = column![
        // Basic Analysis Settings
        text("Analysis Mode").size(16),
        Space::new().height(4),
        row![
            text("Mode:").width(140),
            pick_list(
                analysis_modes.clone(),
                Some(analysis_modes[analysis_mode_idx]),
                move |selected| {
                    let idx = analysis_modes.iter().position(|&m| m == selected).unwrap_or(0);
                    Message::SettingChanged(SettingKey::AnalysisMode, SettingValue::I32(idx as i32))
                }
            ),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        row![
            text("Correlation Method:").width(140),
            pick_list(
                correlation_methods.clone(),
                Some(correlation_methods[corr_method_idx]),
                move |selected| {
                    let idx = correlation_methods
                        .iter()
                        .position(|&m| m == selected)
                        .unwrap_or(0);
                    Message::SettingChanged(SettingKey::CorrelationMethod, SettingValue::I32(idx as i32))
                }
            ),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        row![
            text("Sync Mode:").width(140),
            pick_list(
                sync_modes.clone(),
                Some(sync_modes[sync_mode_idx]),
                move |selected| {
                    let idx = sync_modes.iter().position(|&m| m == selected).unwrap_or(0);
                    Message::SettingChanged(SettingKey::SyncMode, SettingValue::I32(idx as i32))
                }
            ),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        Space::new().height(8),
        Space::new().height(16),
        // Language Settings
        text("Audio Language Filters").size(16),
        Space::new().height(4),
        row![
            text("Source 1 Language:").width(140),
            text_input("e.g. jpn, eng", &lang_source1)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::LangSource1,
                    SettingValue::String(v)
                ))
                .width(120),
            Space::new().width(20),
            text("Other Sources:"),
            text_input("e.g. eng", &lang_others)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::LangOthers,
                    SettingValue::String(v)
                ))
                .width(120),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        Space::new().height(8),
        Space::new().height(16),
        // Chunk Settings
        text("Chunk Settings").size(16),
        Space::new().height(4),
        row![
            text("Chunk Count:").width(140),
            text_input("10", &chunk_count_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::ChunkCount,
                    SettingValue::I32(v.parse().unwrap_or(10))
                ))
                .width(80),
            Space::new().width(20),
            text("Chunk Duration (s):"),
            text_input("15", &chunk_duration_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::ChunkDuration,
                    SettingValue::I32(v.parse().unwrap_or(15))
                ))
                .width(80),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        row![
            text("Min Match %:").width(140),
            text_input("5.0", &min_match_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::MinMatchPct,
                    SettingValue::String(v)
                ))
                .width(80),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        row![
            text("Scan Start %:").width(140),
            text_input("5.0", &scan_start_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::ScanStartPct,
                    SettingValue::String(v)
                ))
                .width(80),
            Space::new().width(20),
            text("Scan End %:"),
            text_input("95.0", &scan_end_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::ScanEndPct,
                    SettingValue::String(v)
                ))
                .width(80),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        Space::new().height(8),
        Space::new().height(16),
        // Filtering Settings
        text("Audio Filtering").size(16),
        Space::new().height(4),
        row![
            text("Filtering Method:").width(140),
            pick_list(
                filtering_methods.clone(),
                Some(filtering_methods[filtering_idx]),
                move |selected| {
                    let idx = filtering_methods
                        .iter()
                        .position(|&m| m == selected)
                        .unwrap_or(0);
                    Message::SettingChanged(SettingKey::FilteringMethod, SettingValue::I32(idx as i32))
                }
            ),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        row![
            text("Low Cutoff (Hz):").width(140),
            text_input("300", &filter_low_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::FilterLowCutoffHz,
                    SettingValue::String(v)
                ))
                .width(80),
            Space::new().width(20),
            text("High Cutoff (Hz):"),
            text_input("3400", &filter_high_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::FilterHighCutoffHz,
                    SettingValue::String(v)
                ))
                .width(80),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        Space::new().height(8),
        checkbox(use_soxr)
            .label("Use SOXR high-quality resampling")
            .on_toggle(|v| Message::SettingChanged(SettingKey::UseSoxr, SettingValue::Bool(v))),
        checkbox(audio_peak_fit)
            .label("Peak fitting (sub-sample accuracy)")
            .on_toggle(|v| Message::SettingChanged(SettingKey::AudioPeakFit, SettingValue::Bool(v))),
        Space::new().height(8),
        Space::new().height(16),
        // Multi-Correlation Settings (moved from separate tab)
        text("Multi-Correlation (Analyze Only)").size(16),
        Space::new().height(4),
        checkbox(multi_corr_enabled)
            .label("Enable multi-correlation comparison")
            .on_toggle(|v| Message::SettingChanged(
                SettingKey::MultiCorrelationEnabled,
                SettingValue::Bool(v)
            )),
        text("Methods to compare:").size(14),
        row![
            checkbox(scc)
                .label("SCC")
                .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrScc, SettingValue::Bool(v))),
            checkbox(gcc_phat)
                .label("GCC-PHAT")
                .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrGccPhat, SettingValue::Bool(v))),
            checkbox(gcc_scot)
                .label("GCC-SCOT")
                .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrGccScot, SettingValue::Bool(v))),
            checkbox(whitened)
                .label("Whitened")
                .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrWhitened, SettingValue::Bool(v))),
        ]
        .spacing(16),
    ]
    .spacing(6);

    scrollable(container(content).padding(16).width(Length::Fill))
        .height(Length::Fill)
        .into()
}

/// Delay Selection tab - includes first stable and early cluster settings
fn delay_selection_tab(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let delay_mode_idx = match settings.analysis.delay_selection_mode {
        vsg_core::models::DelaySelectionMode::Mode => 0,
        vsg_core::models::DelaySelectionMode::ModeClustered => 1,
        vsg_core::models::DelaySelectionMode::ModeEarly => 2,
        vsg_core::models::DelaySelectionMode::FirstStable => 3,
        vsg_core::models::DelaySelectionMode::Average => 4,
    };

    let delay_modes: Vec<&'static str> =
        vec!["Mode", "Mode Clustered", "Mode Early", "First Stable", "Average"];
    let min_chunks_str = settings.analysis.min_accepted_chunks.to_string();

    // First Stable settings
    let first_stable_min_str = settings.analysis.first_stable_min_chunks.to_string();
    let first_stable_skip = settings.analysis.first_stable_skip_unstable;

    // Early Cluster settings
    let early_window_str = settings.analysis.early_cluster_window.to_string();
    let early_threshold_str = settings.analysis.early_cluster_threshold.to_string();

    let content = column![
        text("Delay Selection").size(16),
        Space::new().height(4),
        row![
            text("Selection Mode:").width(160),
            pick_list(
                delay_modes.clone(),
                Some(delay_modes[delay_mode_idx]),
                move |selected| {
                    let idx = delay_modes.iter().position(|&m| m == selected).unwrap_or(0);
                    Message::SettingChanged(SettingKey::DelaySelectionMode, SettingValue::I32(idx as i32))
                }
            ),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        row![
            text("Min Accepted Chunks:").width(160),
            text_input("3", &min_chunks_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::MinAcceptedChunks,
                    SettingValue::I32(v.parse().unwrap_or(3))
                ))
                .width(80),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        Space::new().height(20),
        // First Stable Settings
        text("First Stable Mode Settings").size(16),
        Space::new().height(4),
        row![
            text("Min Consecutive Chunks:").width(160),
            text_input("3", &first_stable_min_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::FirstStableMinChunks,
                    SettingValue::I32(v.parse().unwrap_or(3))
                ))
                .width(80),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        checkbox(first_stable_skip)
            .label("Skip segments below threshold")
            .on_toggle(|v| Message::SettingChanged(
                SettingKey::FirstStableSkipUnstable,
                SettingValue::Bool(v)
            )),
        Space::new().height(20),
        // Early Cluster Settings
        text("Early Cluster Settings").size(16),
        Space::new().height(4),
        row![
            text("Early Window Size:").width(160),
            text_input("10", &early_window_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::EarlyClusterWindow,
                    SettingValue::I32(v.parse().unwrap_or(10))
                ))
                .width(80),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        row![
            text("Early Threshold:").width(160),
            text_input("5", &early_threshold_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::EarlyClusterThreshold,
                    SettingValue::I32(v.parse().unwrap_or(5))
                ))
                .width(80),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
    ]
    .spacing(6);

    scrollable(container(content).padding(16).width(Length::Fill))
        .height(Length::Fill)
        .into()
}

/// Chapters tab - includes snap starts only
fn chapters_tab(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let snap_mode_idx = match settings.chapters.snap_mode {
        vsg_core::models::SnapMode::Previous => 0,
        vsg_core::models::SnapMode::Nearest => 1,
    };

    let snap_modes: Vec<&'static str> = vec!["Previous", "Nearest"];
    let threshold_str = settings.chapters.snap_threshold_ms.to_string();
    let rename = settings.chapters.rename;
    let snap_enabled = settings.chapters.snap_enabled;
    let snap_starts_only = settings.chapters.snap_starts_only;

    let content = column![
        text("Chapter Settings").size(16),
        Space::new().height(8),
        checkbox(rename)
            .label("Rename chapters")
            .on_toggle(|v| Message::SettingChanged(SettingKey::ChapterRename, SettingValue::Bool(v))),
        Space::new().height(20),
        text("Keyframe Snapping").size(16),
        Space::new().height(4),
        checkbox(snap_enabled)
            .label("Snap chapters to keyframes")
            .on_toggle(|v| Message::SettingChanged(SettingKey::ChapterSnap, SettingValue::Bool(v))),
        checkbox(snap_starts_only)
            .label("Snap starts only (not ends)")
            .on_toggle(|v| Message::SettingChanged(SettingKey::SnapStartsOnly, SettingValue::Bool(v))),
        Space::new().height(8),
        row![
            text("Snap Mode:").width(140),
            pick_list(snap_modes.clone(), Some(snap_modes[snap_mode_idx]), move |selected| {
                let idx = snap_modes.iter().position(|&m| m == selected).unwrap_or(0);
                Message::SettingChanged(SettingKey::SnapMode, SettingValue::I32(idx as i32))
            }),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        row![
            text("Snap Threshold (ms):").width(140),
            text_input("250", &threshold_str)
                .on_input(|v| Message::SettingChanged(
                    SettingKey::SnapThresholdMs,
                    SettingValue::I32(v.parse().unwrap_or(250))
                ))
                .width(80),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
    ]
    .spacing(6);

    scrollable(container(content).padding(16).width(Length::Fill))
        .height(Length::Fill)
        .into()
}

/// Merge Behavior tab
fn merge_behavior_tab(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let disable_stats = settings.postprocess.disable_track_stats_tags;
    let disable_compression = settings.postprocess.disable_header_compression;
    let apply_norm = settings.postprocess.apply_dialog_norm;

    let content = column![
        text("Merge Behavior").size(16),
        Space::new().height(8),
        checkbox(disable_stats)
            .label("Disable track stats tags")
            .on_toggle(|v| Message::SettingChanged(
                SettingKey::DisableTrackStats,
                SettingValue::Bool(v)
            )),
        checkbox(disable_compression)
            .label("Disable header compression")
            .on_toggle(|v| Message::SettingChanged(
                SettingKey::DisableHeaderCompression,
                SettingValue::Bool(v)
            )),
        checkbox(apply_norm)
            .label("Apply dialog normalization")
            .on_toggle(|v| Message::SettingChanged(
                SettingKey::ApplyDialogNorm,
                SettingValue::Bool(v)
            )),
    ]
    .spacing(8);

    scrollable(container(content).padding(16).width(Length::Fill))
        .height(Length::Fill)
        .into()
}

/// Logging tab - includes show options
fn logging_tab(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let error_tail_str = settings.logging.error_tail.to_string();
    let progress_step_str = settings.logging.progress_step.to_string();
    let compact = settings.logging.compact;
    let autoscroll = settings.logging.autoscroll;
    let show_options_pretty = settings.logging.show_options_pretty;
    let show_options_json = settings.logging.show_options_json;

    let content = column![
        text("Logging Settings").size(16),
        Space::new().height(8),
        checkbox(compact)
            .label("Compact logging")
            .on_toggle(|v| Message::SettingChanged(SettingKey::CompactLogging, SettingValue::Bool(v))),
        checkbox(autoscroll)
            .label("Autoscroll")
            .on_toggle(|v| Message::SettingChanged(SettingKey::Autoscroll, SettingValue::Bool(v))),
        Space::new().height(8),
        row![
            text("Error tail lines:").width(140),
            text_input("20", &error_tail_str)
                .on_input(|v| {
                    Message::SettingChanged(
                        SettingKey::ErrorTail,
                        SettingValue::I32(v.parse().unwrap_or(20)),
                    )
                })
                .width(80),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        row![
            text("Progress step %:").width(140),
            text_input("20", &progress_step_str)
                .on_input(|v| {
                    Message::SettingChanged(
                        SettingKey::ProgressStep,
                        SettingValue::I32(v.parse().unwrap_or(20)),
                    )
                })
                .width(80),
        ]
        .spacing(8)
        .align_y(Alignment::Center),
        Space::new().height(20),
        text("Debug Output").size(16),
        Space::new().height(4),
        checkbox(show_options_pretty)
            .label("Show mkvmerge options (pretty)")
            .on_toggle(|v| Message::SettingChanged(SettingKey::ShowOptionsPretty, SettingValue::Bool(v))),
        checkbox(show_options_json)
            .label("Show mkvmerge options (JSON)")
            .on_toggle(|v| Message::SettingChanged(SettingKey::ShowOptionsJson, SettingValue::Bool(v))),
    ]
    .spacing(6);

    scrollable(container(content).padding(16).width(Length::Fill))
        .height(Length::Fill)
        .into()
}
