//! Settings dialog
//!
//! Tabbed dialog for application settings, mirroring the PySide6 OptionsDialog

use cosmic::iced::Length;
use cosmic::widget::{self, text, container};
use cosmic::Element;

use crate::config::AppConfig;

/// Tab identifiers for the settings dialog
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SettingsTab {
    Storage,
    Analysis,
    SubtitleCleanup,
    Timing,
    Stepping,
    FrameMatching,
    SubtitleSync,
    Merge,
    Logging,
}

impl Default for SettingsTab {
    fn default() -> Self {
        Self::Storage
    }
}

/// Settings dialog state
#[derive(Default)]
pub struct SettingsDialog {
    /// Currently active tab
    pub active_tab: SettingsTab,
    /// Tab bar model
    pub tabs: widget::segmented_button::SingleSelectModel,
    /// Working copy of config (changes applied on save)
    pub config: AppConfig,
    /// Whether the dialog has unsaved changes
    pub dirty: bool,
}

/// Messages for the settings dialog
#[derive(Debug, Clone)]
pub enum SettingsMessage {
    TabSelected(SettingsTab),

    // Storage tab
    OutputFolderChanged(String),
    TempRootChanged(String),
    VideoDiffPathChanged(String),
    BrowseOutputFolder,
    BrowseTempRoot,
    BrowseVideoDiff,

    // Analysis tab
    CorrelationMethodChanged(String),
    SourceSeparationChanged(String),
    FilteringMethodChanged(String),
    ChunkCountChanged(u32),
    ChunkDurationChanged(u32),
    MinMatchPctChanged(f64),
    MinAcceptedChunksChanged(u32),

    // Timing tab
    TimingFixEnabledToggled(bool),
    OverlapFixEnabledToggled(bool),
    OverlapMinGapChanged(u32),
    ShortDurationFixToggled(bool),
    MinDurationChanged(u32),
    LongDurationFixToggled(bool),
    MaxCpsChanged(f64),

    // Actions
    Save,
    Cancel,
    ResetToDefaults,
}

impl SettingsDialog {
    pub fn new(config: AppConfig) -> Self {
        let mut tabs = widget::segmented_button::SingleSelectModel::default();
        tabs.insert().text("Storage").data(SettingsTab::Storage).activate();
        tabs.insert().text("Analysis").data(SettingsTab::Analysis);
        tabs.insert().text("Subtitle Cleanup").data(SettingsTab::SubtitleCleanup);
        tabs.insert().text("Timing").data(SettingsTab::Timing);
        tabs.insert().text("Stepping").data(SettingsTab::Stepping);
        tabs.insert().text("Frame Matching").data(SettingsTab::FrameMatching);
        tabs.insert().text("Subtitle Sync").data(SettingsTab::SubtitleSync);
        tabs.insert().text("Merge").data(SettingsTab::Merge);
        tabs.insert().text("Logging").data(SettingsTab::Logging);

        Self {
            active_tab: SettingsTab::Storage,
            tabs,
            config,
            dirty: false,
        }
    }

    /// View for the current tab
    pub fn view_tab(&self) -> Element<SettingsMessage> {
        match self.active_tab {
            SettingsTab::Storage => self.view_storage_tab(),
            SettingsTab::Analysis => self.view_analysis_tab(),
            SettingsTab::SubtitleCleanup => self.view_cleanup_tab(),
            SettingsTab::Timing => self.view_timing_tab(),
            _ => self.view_placeholder_tab(),
        }
    }

    fn view_storage_tab(&self) -> Element<SettingsMessage> {
        let output_folder = self.config.output_folder
            .as_ref()
            .and_then(|p| p.to_str())
            .unwrap_or("");
        let temp_root = self.config.temp_root
            .as_ref()
            .and_then(|p| p.to_str())
            .unwrap_or("");

        widget::column()
            .push(self.form_row(
                "Output Directory:",
                widget::text_input("", output_folder)
                    .on_input(SettingsMessage::OutputFolderChanged),
                Some(SettingsMessage::BrowseOutputFolder),
            ))
            .push(self.form_row(
                "Temporary Directory:",
                widget::text_input("", temp_root)
                    .on_input(SettingsMessage::TempRootChanged),
                Some(SettingsMessage::BrowseTempRoot),
            ))
            .spacing(8)
            .into()
    }

    fn view_analysis_tab(&self) -> Element<SettingsMessage> {
        widget::column()
            .push(text("Step 1: Audio Pre-Processing").size(14))
            .push(text("Step 2: Core Analysis Engine").size(14))
            // TODO: Add actual form fields
            .push(text("Analysis settings will be implemented here"))
            .spacing(12)
            .into()
    }

    fn view_cleanup_tab(&self) -> Element<SettingsMessage> {
        widget::column()
            .push(widget::checkbox(
                "Enable post-OCR cleanup",
                self.config.ocr_cleanup_enabled,
            ).on_toggle(|_| SettingsMessage::Cancel)) // TODO: proper message
            .push(widget::checkbox(
                "Normalize ellipsis (...)",
                self.config.ocr_cleanup_normalize_ellipsis,
            ).on_toggle(|_| SettingsMessage::Cancel))
            .spacing(8)
            .into()
    }

    fn view_timing_tab(&self) -> Element<SettingsMessage> {
        widget::column()
            .push(widget::checkbox(
                "Enable subtitle timing corrections",
                self.config.timing_fix_enabled,
            ).on_toggle(SettingsMessage::TimingFixEnabledToggled))

            // Overlaps group
            .push(text("Fix Overlapping Display Times").size(14))
            .push(widget::checkbox(
                "Enable",
                self.config.timing_fix_overlaps,
            ).on_toggle(SettingsMessage::OverlapFixEnabledToggled))

            // Short durations group
            .push(text("Fix Short Display Times").size(14))
            .push(widget::checkbox(
                "Enable",
                self.config.timing_fix_short_durations,
            ).on_toggle(SettingsMessage::ShortDurationFixToggled))

            // Long durations group
            .push(text("Fix Long Display Times (based on Reading Speed)").size(14))
            .push(widget::checkbox(
                "Enable",
                self.config.timing_fix_long_durations,
            ).on_toggle(SettingsMessage::LongDurationFixToggled))
            .spacing(8)
            .into()
    }

    fn view_placeholder_tab(&self) -> Element<SettingsMessage> {
        widget::column()
            .push(text("This tab is not yet implemented"))
            .into()
    }

    /// Create a form row with label, input, and optional browse button
    fn form_row<'a>(
        &self,
        label: &'a str,
        input: impl Into<Element<'a, SettingsMessage>>,
        browse_msg: Option<SettingsMessage>,
    ) -> Element<'a, SettingsMessage> {
        let mut r = widget::row()
            .push(text(label).width(Length::Fixed(150.0)))
            .push(container(input).width(Length::Fill))
            .spacing(8);

        if let Some(msg) = browse_msg {
            r = r.push(
                widget::button::standard("Browse...")
                    .on_press(msg)
            );
        }

        r.into()
    }
}
