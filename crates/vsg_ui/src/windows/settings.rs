//! Settings window view.
//!
//! Multi-tab settings dialog with all configuration options.

use cosmic::iced::{Alignment, Length};
use cosmic::prelude::*;
use cosmic::{widget, Element};

use crate::app::{App, FolderType, Message, SettingKey, SettingValue};

/// Build the settings window view.
pub fn view(app: &App) -> Element<Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let Some(settings) = &app.pending_settings else {
        return widget::text::body("No settings loaded").into();
    };

    let content = widget::column()
        .push(widget::text::title3("Settings"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_m.into())))
        .push(
            widget::scrollable(
                widget::column()
                    .push(storage_section(settings))
                    .push(widget::vertical_space().height(Length::Fixed(spacing.space_l.into())))
                    .push(logging_section(settings))
                    .push(widget::vertical_space().height(Length::Fixed(spacing.space_l.into())))
                    .push(analysis_section(settings))
                    .push(widget::vertical_space().height(Length::Fixed(spacing.space_l.into())))
                    .push(multi_correlation_section(settings))
                    .push(widget::vertical_space().height(Length::Fixed(spacing.space_l.into())))
                    .push(delay_selection_section(settings))
                    .push(widget::vertical_space().height(Length::Fixed(spacing.space_l.into())))
                    .push(chapters_section(settings))
                    .push(widget::vertical_space().height(Length::Fixed(spacing.space_l.into())))
                    .push(postprocess_section(settings))
                    .spacing(spacing.space_xxs)
                    .padding(spacing.space_s)
            )
            .height(Length::Fill)
        )
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_m.into())))
        .push(
            widget::row()
                .push(widget::horizontal_space())
                .push(
                    widget::button::standard("Cancel")
                        .on_press(Message::CloseSettings)
                )
                .push(
                    widget::button::suggested("Save")
                        .on_press(Message::SaveSettings)
                )
                .spacing(spacing.space_s)
        )
        .spacing(spacing.space_xxs)
        .padding(spacing.space_l);

    widget::container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}

fn storage_section(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    widget::column()
        .push(widget::text::title4("Storage & Tools"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(folder_row("Output Folder:", &settings.paths.output_folder, FolderType::Output))
        .push(folder_row("Temp Folder:", &settings.paths.temp_root, FolderType::Temp))
        .push(folder_row("Logs Folder:", &settings.paths.logs_folder, FolderType::Logs))
        .spacing(spacing.space_xxs)
        .into()
}

fn folder_row(label: &str, path: &str, folder_type: FolderType) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let key = match folder_type {
        FolderType::Output => SettingKey::OutputFolder,
        FolderType::Temp => SettingKey::TempRoot,
        FolderType::Logs => SettingKey::LogsFolder,
    };

    let label_owned = label.to_string();
    let path_owned = path.to_string();

    widget::row()
        .push(
            widget::text::body(label_owned)
                .width(Length::Fixed(120.0))
        )
        .push(
            widget::text_input::text_input("", path_owned)
                .on_input(move |s| Message::SettingChanged(key.clone(), SettingValue::String(s)))
                .width(Length::Fill)
        )
        .push(
            widget::button::standard("Browse")
                .on_press(Message::BrowseFolder(folder_type))
        )
        .spacing(spacing.space_s)
        .align_y(Alignment::Center)
        .into()
}

fn logging_section(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let error_tail_str = settings.logging.error_tail.to_string();
    let progress_step_str = settings.logging.progress_step.to_string();

    widget::column()
        .push(widget::text::title4("Logging"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::row()
                .push(
                    widget::checkbox("Compact logging", settings.logging.compact)
                        .on_toggle(|v| Message::SettingChanged(SettingKey::CompactLogging, SettingValue::Bool(v)))
                )
                .push(widget::horizontal_space().width(Length::Fixed(spacing.space_l.into())))
                .push(
                    widget::checkbox("Autoscroll", settings.logging.autoscroll)
                        .on_toggle(|v| Message::SettingChanged(SettingKey::Autoscroll, SettingValue::Bool(v)))
                )
        )
        .push(
            widget::row()
                .push(widget::text::body("Error tail:"))
                .push(
                    widget::text_input::text_input("0", error_tail_str)
                        .on_input(|v| {
                            Message::SettingChanged(SettingKey::ErrorTail, SettingValue::I32(v.parse().unwrap_or(0)))
                        })
                        .width(Length::Fixed(60.0))
                )
                .push(widget::horizontal_space().width(Length::Fixed(spacing.space_l.into())))
                .push(widget::text::body("Progress step:"))
                .push(
                    widget::text_input::text_input("1", progress_step_str)
                        .on_input(|v| {
                            Message::SettingChanged(SettingKey::ProgressStep, SettingValue::I32(v.parse().unwrap_or(1)))
                        })
                        .width(Length::Fixed(60.0))
                )
                .spacing(spacing.space_s)
                .align_y(Alignment::Center)
        )
        .spacing(spacing.space_xxs)
        .into()
}

// Static arrays for dropdown options
static ANALYSIS_MODES: &[&str] = &["Audio Correlation", "Video Diff"];
static CORRELATION_METHODS: &[&str] = &["SCC", "GCC-PHAT", "GCC-SCOT", "Whitened"];
static SYNC_MODES: &[&str] = &["Positive Only", "Allow Negative"];
static FILTERING_METHODS: &[&str] = &["None", "Low Pass", "Band Pass", "High Pass"];

fn analysis_section(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let analysis_mode_idx = match settings.analysis.mode {
        vsg_core::models::AnalysisMode::AudioCorrelation => Some(0),
        vsg_core::models::AnalysisMode::VideoDiff => Some(1),
    };

    let corr_method_idx = match settings.analysis.correlation_method {
        vsg_core::models::CorrelationMethod::Scc => Some(0),
        vsg_core::models::CorrelationMethod::GccPhat => Some(1),
        vsg_core::models::CorrelationMethod::GccScot => Some(2),
        vsg_core::models::CorrelationMethod::Whitened => Some(3),
    };

    let sync_mode_idx = match settings.analysis.sync_mode {
        vsg_core::models::SyncMode::PositiveOnly => Some(0),
        vsg_core::models::SyncMode::AllowNegative => Some(1),
    };

    let filtering_idx = match settings.analysis.filtering_method {
        vsg_core::models::FilteringMethod::None => Some(0),
        vsg_core::models::FilteringMethod::LowPass => Some(1),
        vsg_core::models::FilteringMethod::BandPass => Some(2),
        vsg_core::models::FilteringMethod::HighPass => Some(3),
    };

    widget::column()
        .push(widget::text::title4("Analysis"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::row()
                .push(widget::text::body("Analysis Mode:").width(Length::Fixed(140.0)))
                .push(
                    widget::dropdown(ANALYSIS_MODES, analysis_mode_idx, |idx| {
                        Message::SettingChanged(SettingKey::AnalysisMode, SettingValue::I32(idx as i32))
                    })
                )
                .push(widget::horizontal_space().width(Length::Fixed(spacing.space_l.into())))
                .push(widget::text::body("Correlation:"))
                .push(
                    widget::dropdown(CORRELATION_METHODS, corr_method_idx, |idx| {
                        Message::SettingChanged(SettingKey::CorrelationMethod, SettingValue::I32(idx as i32))
                    })
                )
                .spacing(spacing.space_s)
                .align_y(Alignment::Center)
        )
        .push(
            widget::row()
                .push(widget::text::body("Sync Mode:").width(Length::Fixed(140.0)))
                .push(
                    widget::dropdown(SYNC_MODES, sync_mode_idx, |idx| {
                        Message::SettingChanged(SettingKey::SyncMode, SettingValue::I32(idx as i32))
                    })
                )
                .push(widget::horizontal_space().width(Length::Fixed(spacing.space_l.into())))
                .push(widget::text::body("Filtering:"))
                .push(
                    widget::dropdown(FILTERING_METHODS, filtering_idx, |idx| {
                        Message::SettingChanged(SettingKey::FilteringMethod, SettingValue::I32(idx as i32))
                    })
                )
                .spacing(spacing.space_s)
                .align_y(Alignment::Center)
        )
        .push(
            widget::row()
                .push(widget::text::body("Chunk Count:").width(Length::Fixed(140.0)))
                .push(
                    widget::text_input::text_input("10", settings.analysis.chunk_count.to_string())
                        .on_input(|v| Message::SettingChanged(SettingKey::ChunkCount, SettingValue::I32(v.parse().unwrap_or(10))))
                        .width(Length::Fixed(60.0))
                )
                .push(widget::horizontal_space().width(Length::Fixed(spacing.space_l.into())))
                .push(widget::text::body("Chunk Duration:"))
                .push(
                    widget::text_input::text_input("20", settings.analysis.chunk_duration.to_string())
                        .on_input(|v| Message::SettingChanged(SettingKey::ChunkDuration, SettingValue::I32(v.parse().unwrap_or(20))))
                        .width(Length::Fixed(60.0))
                )
                .spacing(spacing.space_s)
                .align_y(Alignment::Center)
        )
        .push(
            widget::checkbox("Peak fitting", settings.analysis.audio_peak_fit)
                .on_toggle(|v| Message::SettingChanged(SettingKey::AudioPeakFit, SettingValue::Bool(v)))
        )
        .spacing(spacing.space_xxs)
        .into()
}

fn multi_correlation_section(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    widget::column()
        .push(widget::text::title4("Multi-Correlation"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::checkbox("Enable multi-correlation", settings.analysis.multi_correlation_enabled)
                .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrelationEnabled, SettingValue::Bool(v)))
        )
        .push(
            widget::row()
                .push(
                    widget::checkbox("SCC", settings.analysis.multi_corr_scc)
                        .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrScc, SettingValue::Bool(v)))
                )
                .push(
                    widget::checkbox("GCC-PHAT", settings.analysis.multi_corr_gcc_phat)
                        .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrGccPhat, SettingValue::Bool(v)))
                )
                .push(
                    widget::checkbox("GCC-SCOT", settings.analysis.multi_corr_gcc_scot)
                        .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrGccScot, SettingValue::Bool(v)))
                )
                .push(
                    widget::checkbox("Whitened", settings.analysis.multi_corr_whitened)
                        .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrWhitened, SettingValue::Bool(v)))
                )
                .spacing(spacing.space_m)
        )
        .spacing(spacing.space_xxs)
        .into()
}

static DELAY_MODES: &[&str] = &["Mode", "Mode Clustered", "Mode Early", "First Stable", "Average"];

fn delay_selection_section(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let delay_mode_idx = match settings.analysis.delay_selection_mode {
        vsg_core::models::DelaySelectionMode::Mode => Some(0),
        vsg_core::models::DelaySelectionMode::ModeClustered => Some(1),
        vsg_core::models::DelaySelectionMode::ModeEarly => Some(2),
        vsg_core::models::DelaySelectionMode::FirstStable => Some(3),
        vsg_core::models::DelaySelectionMode::Average => Some(4),
    };

    widget::column()
        .push(widget::text::title4("Delay Selection"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::row()
                .push(widget::text::body("Mode:").width(Length::Fixed(140.0)))
                .push(
                    widget::dropdown(DELAY_MODES, delay_mode_idx, |idx| {
                        Message::SettingChanged(SettingKey::DelaySelectionMode, SettingValue::I32(idx as i32))
                    })
                )
                .spacing(spacing.space_s)
                .align_y(Alignment::Center)
        )
        .push(
            widget::row()
                .push(widget::text::body("Min Accepted Chunks:").width(Length::Fixed(160.0)))
                .push(
                    widget::text_input::text_input("3", settings.analysis.min_accepted_chunks.to_string())
                        .on_input(|v| Message::SettingChanged(SettingKey::MinAcceptedChunks, SettingValue::I32(v.parse().unwrap_or(3))))
                        .width(Length::Fixed(60.0))
                )
                .spacing(spacing.space_s)
                .align_y(Alignment::Center)
        )
        .spacing(spacing.space_xxs)
        .into()
}

static SNAP_MODES: &[&str] = &["Previous", "Nearest"];

fn chapters_section(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    let snap_mode_idx = match settings.chapters.snap_mode {
        vsg_core::models::SnapMode::Previous => Some(0),
        vsg_core::models::SnapMode::Nearest => Some(1),
    };

    widget::column()
        .push(widget::text::title4("Chapters"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::row()
                .push(
                    widget::checkbox("Rename chapters", settings.chapters.rename)
                        .on_toggle(|v| Message::SettingChanged(SettingKey::ChapterRename, SettingValue::Bool(v)))
                )
                .push(widget::horizontal_space().width(Length::Fixed(spacing.space_l.into())))
                .push(
                    widget::checkbox("Snap to keyframes", settings.chapters.snap_enabled)
                        .on_toggle(|v| Message::SettingChanged(SettingKey::ChapterSnap, SettingValue::Bool(v)))
                )
        )
        .push(
            widget::row()
                .push(widget::text::body("Snap Mode:").width(Length::Fixed(120.0)))
                .push(
                    widget::dropdown(SNAP_MODES, snap_mode_idx, |idx| {
                        Message::SettingChanged(SettingKey::SnapMode, SettingValue::I32(idx as i32))
                    })
                )
                .push(widget::horizontal_space().width(Length::Fixed(spacing.space_l.into())))
                .push(widget::text::body("Threshold (ms):"))
                .push(
                    widget::text_input::text_input("500", settings.chapters.snap_threshold_ms.to_string())
                        .on_input(|v| Message::SettingChanged(SettingKey::SnapThresholdMs, SettingValue::I32(v.parse().unwrap_or(500))))
                        .width(Length::Fixed(80.0))
                )
                .spacing(spacing.space_s)
                .align_y(Alignment::Center)
        )
        .spacing(spacing.space_xxs)
        .into()
}

fn postprocess_section(settings: &vsg_core::config::Settings) -> Element<'static, Message> {
    let spacing = cosmic::theme::active().cosmic().spacing;

    widget::column()
        .push(widget::text::title4("Merge Behavior"))
        .push(widget::vertical_space().height(Length::Fixed(spacing.space_s.into())))
        .push(
            widget::checkbox("Disable track stats tags", settings.postprocess.disable_track_stats_tags)
                .on_toggle(|v| Message::SettingChanged(SettingKey::DisableTrackStats, SettingValue::Bool(v)))
        )
        .push(
            widget::checkbox("Disable header compression", settings.postprocess.disable_header_compression)
                .on_toggle(|v| Message::SettingChanged(SettingKey::DisableHeaderCompression, SettingValue::Bool(v)))
        )
        .push(
            widget::checkbox("Apply dialog normalization", settings.postprocess.apply_dialog_norm)
                .on_toggle(|v| Message::SettingChanged(SettingKey::ApplyDialogNorm, SettingValue::Bool(v)))
        )
        .spacing(spacing.space_xxs)
        .into()
}
