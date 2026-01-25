//! Settings window view.
//!
//! Multi-tab settings dialog with all configuration options.

use cosmic::iced::alignment::Vertical;
use cosmic::iced::Length;
use cosmic::widget::{self, button, checkbox, column, container, dropdown, horizontal_space, row, scrollable, spin_button, text, text_input, vertical_space};
use cosmic::Element;

use crate::app::{App, FolderType, Message, SettingKey, SettingValue};
use crate::theme::{font, spacing};

/// Build the settings window view.
pub fn view(app: &App) -> Element<Message> {
    let Some(settings) = &app.pending_settings else {
        return text("No settings loaded").into();
    };

    let content = column![
        text("Settings").size(font::HEADER),
        vertical_space().height(spacing::MD),
        scrollable(
            column![
                storage_section(settings),
                vertical_space().height(spacing::LG),
                logging_section(settings),
                vertical_space().height(spacing::LG),
                analysis_section(settings),
                vertical_space().height(spacing::LG),
                multi_correlation_section(settings),
                vertical_space().height(spacing::LG),
                delay_selection_section(settings),
                vertical_space().height(spacing::LG),
                chapters_section(settings),
                vertical_space().height(spacing::LG),
                postprocess_section(settings),
            ]
            .spacing(spacing::XS)
            .padding(spacing::SM)
        )
        .height(Length::Fill),
        vertical_space().height(spacing::MD),
        row![
            horizontal_space(),
            button(text("Cancel").size(font::NORMAL))
                .on_press(Message::CloseSettings)
                .padding([spacing::SM, spacing::LG]),
            button(text("Save").size(font::NORMAL))
                .on_press(Message::SaveSettings)
                .padding([spacing::SM, spacing::LG]),
        ]
        .spacing(spacing::SM),
    ]
    .spacing(spacing::XS)
    .padding(spacing::LG);

    container(content)
        .width(Length::Fill)
        .height(Length::Fill)
        .into()
}

fn storage_section(settings: &vsg_core::config::Settings) -> Element<Message> {
    column![
        text("Storage & Tools").size(font::LG),
        vertical_space().height(spacing::SM),
        folder_row("Output Folder:", &settings.paths.output_folder, FolderType::Output),
        folder_row("Temp Folder:", &settings.paths.temp_root, FolderType::Temp),
        folder_row("Logs Folder:", &settings.paths.logs_folder, FolderType::Logs),
    ]
    .spacing(spacing::XS)
    .into()
}

fn folder_row(label: &str, path: &str, folder_type: FolderType) -> Element<Message> {
    let key = match folder_type {
        FolderType::Output => SettingKey::OutputFolder,
        FolderType::Temp => SettingKey::TempRoot,
        FolderType::Logs => SettingKey::LogsFolder,
    };
    row![
        text(label).size(font::NORMAL).width(Length::Fixed(120.0)),
        text_input("", path)
            .on_input(move |s| Message::SettingChanged(key.clone(), SettingValue::String(s)))
            .width(Length::Fill)
            .size(font::NORMAL),
        button(text("Browse").size(font::SM))
            .on_press(Message::BrowseFolder(folder_type))
            .padding([spacing::XS, spacing::SM]),
    ]
    .spacing(spacing::SM)
    .align_y(Vertical::Center)
    .into()
}

fn logging_section(settings: &vsg_core::config::Settings) -> Element<Message> {
    column![
        text("Logging").size(font::LG),
        vertical_space().height(spacing::SM),
        row![
            checkbox("Compact logging", settings.logging.compact)
                .on_toggle(|v| Message::SettingChanged(SettingKey::CompactLogging, SettingValue::Bool(v)))
                .text_size(font::NORMAL),
            horizontal_space().width(spacing::LG),
            checkbox("Autoscroll", settings.logging.autoscroll)
                .on_toggle(|v| Message::SettingChanged(SettingKey::Autoscroll, SettingValue::Bool(v)))
                .text_size(font::NORMAL),
        ],
        row![
            text("Error tail:").size(font::NORMAL),
            spin_button("", settings.logging.error_tail as i32)
                .on_change(|v| Message::SettingChanged(SettingKey::ErrorTail, SettingValue::I32(v)))
                .min(0)
                .max(100)
                .step(1),
            horizontal_space().width(spacing::LG),
            text("Progress step:").size(font::NORMAL),
            spin_button("", settings.logging.progress_step as i32)
                .on_change(|v| Message::SettingChanged(SettingKey::ProgressStep, SettingValue::I32(v)))
                .min(1)
                .max(100)
                .step(1),
        ]
        .spacing(spacing::SM)
        .align_y(Vertical::Center),
    ]
    .spacing(spacing::XS)
    .into()
}

fn analysis_section(settings: &vsg_core::config::Settings) -> Element<Message> {
    let analysis_modes = vec!["Audio Correlation", "Video Diff"];
    let analysis_mode_idx = match settings.analysis.mode {
        vsg_core::models::AnalysisMode::AudioCorrelation => 0,
        vsg_core::models::AnalysisMode::VideoDiff => 1,
    };
    let correlation_methods = vec!["SCC", "GCC-PHAT", "GCC-SCOT", "Whitened"];
    let corr_method_idx = match settings.analysis.correlation_method {
        vsg_core::models::CorrelationMethod::Scc => 0,
        vsg_core::models::CorrelationMethod::GccPhat => 1,
        vsg_core::models::CorrelationMethod::GccScot => 2,
        vsg_core::models::CorrelationMethod::Whitened => 3,
    };
    let sync_modes = vec!["Positive Only", "Allow Negative"];
    let sync_mode_idx = match settings.analysis.sync_mode {
        vsg_core::models::SyncMode::PositiveOnly => 0,
        vsg_core::models::SyncMode::AllowNegative => 1,
    };
    let filtering_methods = vec!["None", "Low Pass", "Band Pass", "High Pass"];
    let filtering_idx = match settings.analysis.filtering_method {
        vsg_core::models::FilteringMethod::None => 0,
        vsg_core::models::FilteringMethod::LowPass => 1,
        vsg_core::models::FilteringMethod::BandPass => 2,
        vsg_core::models::FilteringMethod::HighPass => 3,
    };

    column![
        text("Analysis").size(font::LG),
        vertical_space().height(spacing::SM),
        row![
            text("Analysis Mode:").size(font::NORMAL).width(Length::Fixed(140.0)),
            dropdown(&analysis_modes, Some(analysis_mode_idx), |idx| {
                Message::SettingChanged(SettingKey::AnalysisMode, SettingValue::I32(idx as i32))
            }),
            horizontal_space().width(spacing::LG),
            text("Correlation:").size(font::NORMAL),
            dropdown(&correlation_methods, Some(corr_method_idx), |idx| {
                Message::SettingChanged(SettingKey::CorrelationMethod, SettingValue::I32(idx as i32))
            }),
        ]
        .spacing(spacing::SM)
        .align_y(Vertical::Center),
        row![
            text("Sync Mode:").size(font::NORMAL).width(Length::Fixed(140.0)),
            dropdown(&sync_modes, Some(sync_mode_idx), |idx| {
                Message::SettingChanged(SettingKey::SyncMode, SettingValue::I32(idx as i32))
            }),
            horizontal_space().width(spacing::LG),
            text("Filtering:").size(font::NORMAL),
            dropdown(&filtering_methods, Some(filtering_idx), |idx| {
                Message::SettingChanged(SettingKey::FilteringMethod, SettingValue::I32(idx as i32))
            }),
        ]
        .spacing(spacing::SM)
        .align_y(Vertical::Center),
        row![
            text("Chunk Count:").size(font::NORMAL).width(Length::Fixed(140.0)),
            spin_button("", settings.analysis.chunk_count as i32)
                .on_change(|v| Message::SettingChanged(SettingKey::ChunkCount, SettingValue::I32(v)))
                .min(1)
                .max(50)
                .step(1),
            horizontal_space().width(spacing::LG),
            text("Chunk Duration:").size(font::NORMAL),
            spin_button("", settings.analysis.chunk_duration as i32)
                .on_change(|v| Message::SettingChanged(SettingKey::ChunkDuration, SettingValue::I32(v)))
                .min(1)
                .max(120)
                .step(1),
        ]
        .spacing(spacing::SM)
        .align_y(Vertical::Center),
        checkbox("Peak fitting", settings.analysis.audio_peak_fit)
            .on_toggle(|v| Message::SettingChanged(SettingKey::AudioPeakFit, SettingValue::Bool(v)))
            .text_size(font::NORMAL),
    ]
    .spacing(spacing::XS)
    .into()
}

fn multi_correlation_section(settings: &vsg_core::config::Settings) -> Element<Message> {
    column![
        text("Multi-Correlation").size(font::LG),
        vertical_space().height(spacing::SM),
        checkbox("Enable multi-correlation", settings.analysis.multi_correlation_enabled)
            .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrelationEnabled, SettingValue::Bool(v)))
            .text_size(font::NORMAL),
        row![
            checkbox("SCC", settings.analysis.multi_corr_scc)
                .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrScc, SettingValue::Bool(v)))
                .text_size(font::NORMAL),
            checkbox("GCC-PHAT", settings.analysis.multi_corr_gcc_phat)
                .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrGccPhat, SettingValue::Bool(v)))
                .text_size(font::NORMAL),
            checkbox("GCC-SCOT", settings.analysis.multi_corr_gcc_scot)
                .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrGccScot, SettingValue::Bool(v)))
                .text_size(font::NORMAL),
            checkbox("Whitened", settings.analysis.multi_corr_whitened)
                .on_toggle(|v| Message::SettingChanged(SettingKey::MultiCorrWhitened, SettingValue::Bool(v)))
                .text_size(font::NORMAL),
        ]
        .spacing(spacing::MD),
    ]
    .spacing(spacing::XS)
    .into()
}

fn delay_selection_section(settings: &vsg_core::config::Settings) -> Element<Message> {
    let delay_modes = vec!["Mode", "Mode Clustered", "Mode Early", "First Stable", "Average"];
    let delay_mode_idx = match settings.analysis.delay_selection_mode {
        vsg_core::models::DelaySelectionMode::Mode => 0,
        vsg_core::models::DelaySelectionMode::ModeClustered => 1,
        vsg_core::models::DelaySelectionMode::ModeEarly => 2,
        vsg_core::models::DelaySelectionMode::FirstStable => 3,
        vsg_core::models::DelaySelectionMode::Average => 4,
    };
    column![
        text("Delay Selection").size(font::LG),
        vertical_space().height(spacing::SM),
        row![
            text("Mode:").size(font::NORMAL).width(Length::Fixed(140.0)),
            dropdown(&delay_modes, Some(delay_mode_idx), |idx| {
                Message::SettingChanged(SettingKey::DelaySelectionMode, SettingValue::I32(idx as i32))
            }),
        ]
        .spacing(spacing::SM)
        .align_y(Vertical::Center),
        row![
            text("Min Accepted Chunks:").size(font::NORMAL).width(Length::Fixed(160.0)),
            spin_button("", settings.analysis.min_accepted_chunks as i32)
                .on_change(|v| Message::SettingChanged(SettingKey::MinAcceptedChunks, SettingValue::I32(v)))
                .min(1)
                .max(50)
                .step(1),
        ]
        .spacing(spacing::SM)
        .align_y(Vertical::Center),
    ]
    .spacing(spacing::XS)
    .into()
}

fn chapters_section(settings: &vsg_core::config::Settings) -> Element<Message> {
    let snap_modes = vec!["Previous", "Nearest"];
    let snap_mode_idx = match settings.chapters.snap_mode {
        vsg_core::models::SnapMode::Previous => 0,
        vsg_core::models::SnapMode::Nearest => 1,
    };
    column![
        text("Chapters").size(font::LG),
        vertical_space().height(spacing::SM),
        row![
            checkbox("Rename chapters", settings.chapters.rename)
                .on_toggle(|v| Message::SettingChanged(SettingKey::ChapterRename, SettingValue::Bool(v)))
                .text_size(font::NORMAL),
            horizontal_space().width(spacing::LG),
            checkbox("Snap to keyframes", settings.chapters.snap_enabled)
                .on_toggle(|v| Message::SettingChanged(SettingKey::ChapterSnap, SettingValue::Bool(v)))
                .text_size(font::NORMAL),
        ],
        row![
            text("Snap Mode:").size(font::NORMAL).width(Length::Fixed(120.0)),
            dropdown(&snap_modes, Some(snap_mode_idx), |idx| {
                Message::SettingChanged(SettingKey::SnapMode, SettingValue::I32(idx as i32))
            }),
            horizontal_space().width(spacing::LG),
            text("Threshold (ms):").size(font::NORMAL),
            spin_button("", settings.chapters.snap_threshold_ms as i32)
                .on_change(|v| Message::SettingChanged(SettingKey::SnapThresholdMs, SettingValue::I32(v)))
                .min(0)
                .max(5000)
                .step(100),
        ]
        .spacing(spacing::SM)
        .align_y(Vertical::Center),
    ]
    .spacing(spacing::XS)
    .into()
}

fn postprocess_section(settings: &vsg_core::config::Settings) -> Element<Message> {
    column![
        text("Merge Behavior").size(font::LG),
        vertical_space().height(spacing::SM),
        checkbox("Disable track stats tags", settings.postprocess.disable_track_stats_tags)
            .on_toggle(|v| Message::SettingChanged(SettingKey::DisableTrackStats, SettingValue::Bool(v)))
            .text_size(font::NORMAL),
        checkbox("Disable header compression", settings.postprocess.disable_header_compression)
            .on_toggle(|v| Message::SettingChanged(SettingKey::DisableHeaderCompression, SettingValue::Bool(v)))
            .text_size(font::NORMAL),
        checkbox("Apply dialog normalization", settings.postprocess.apply_dialog_norm)
            .on_toggle(|v| Message::SettingChanged(SettingKey::ApplyDialogNorm, SettingValue::Bool(v)))
            .text_size(font::NORMAL),
    ]
    .spacing(spacing::XS)
    .into()
}
