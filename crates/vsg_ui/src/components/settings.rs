//! Settings dialog component.
//!
//! Multi-tab settings dialog with all configuration options.

use gtk::prelude::*;
use relm4::prelude::*;
use relm4::{Component, ComponentParts, ComponentSender};

use vsg_core::config::Settings;

/// Output messages from the settings dialog.
#[derive(Debug)]
pub enum SettingsOutput {
    Saved(Settings),
    Cancelled,
}

/// Input messages for the settings dialog.
#[derive(Debug)]
pub enum SettingsMsg {
    // Tab navigation
    SwitchTab(u32),

    // Storage paths
    OutputFolderChanged(String),
    TempFolderChanged(String),
    LogsFolderChanged(String),
    BrowseOutput,
    BrowseTemp,
    BrowseLogs,
    FolderSelected(FolderType, Option<std::path::PathBuf>),

    // Analysis settings
    AnalysisModeChanged(u32),
    CorrelationMethodChanged(u32),
    SyncModeChanged(u32),
    ChunkCountChanged(String),
    ChunkDurationChanged(String),
    MinMatchPctChanged(String),
    ScanStartChanged(String),
    ScanEndChanged(String),
    FilteringMethodChanged(u32),
    FilterLowChanged(String),
    FilterHighChanged(String),
    UseSoxrChanged(bool),
    AudioPeakFitChanged(bool),
    LangSource1Changed(String),
    LangOthersChanged(String),

    // Multi-correlation
    MultiCorrEnabledChanged(bool),
    MultiCorrSccChanged(bool),
    MultiCorrPhatChanged(bool),
    MultiCorrScotChanged(bool),
    MultiCorrWhitenedChanged(bool),

    // Delay selection
    DelayModeChanged(u32),
    MinAcceptedChunksChanged(String),
    FirstStableMinChunksChanged(String),
    FirstStableSkipChanged(bool),
    EarlyClusterWindowChanged(String),
    EarlyClusterThresholdChanged(String),

    // Chapters
    ChapterRenameChanged(bool),
    ChapterSnapChanged(bool),
    SnapModeChanged(u32),
    SnapThresholdChanged(String),
    SnapStartsOnlyChanged(bool),

    // Merge behavior
    DisableTrackStatsChanged(bool),
    DisableHeaderCompressionChanged(bool),
    ApplyDialogNormChanged(bool),

    // Logging
    CompactLoggingChanged(bool),
    AutoscrollChanged(bool),
    ErrorTailChanged(String),
    ProgressStepChanged(String),
    ShowOptionsPrettyChanged(bool),
    ShowOptionsJsonChanged(bool),

    // Dialog actions
    Save,
    Cancel,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FolderType {
    Output,
    Temp,
    Logs,
}

/// Settings dialog state.
pub struct SettingsDialog {
    settings: Settings,
    active_tab: u32,
}

#[relm4::component(pub)]
impl Component for SettingsDialog {
    type Init = Settings;
    type Input = SettingsMsg;
    type Output = SettingsOutput;
    type CommandOutput = ();

    view! {
        adw::Window {
            set_title: Some("Settings"),
            set_default_width: 700,
            set_default_height: 600,
            set_modal: true,

            #[wrap(Some)]
            set_content = &gtk::Box {
                set_orientation: gtk::Orientation::Vertical,

                adw::HeaderBar {
                    #[wrap(Some)]
                    set_title_widget = &gtk::Label {
                        set_label: "Application Settings",
                    },
                },

                gtk::Box {
                    set_orientation: gtk::Orientation::Vertical,
                    set_spacing: 12,
                    set_margin_all: 16,
                    set_vexpand: true,

                    // Tab view using AdwViewStack
                    #[name = "stack"]
                    adw::ViewStack {
                        set_vexpand: true,

                        add_titled[Some("storage"), "Storage"] = &gtk::ScrolledWindow {
                            set_vexpand: true,
                            set_hexpand: true,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Vertical,
                                set_spacing: 12,
                                set_margin_all: 16,

                                gtk::Label {
                                    set_label: "Storage Paths",
                                    set_xalign: 0.0,
                                    add_css_class: "title-3",
                                },

                                // Output folder
                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 8,

                                    gtk::Label {
                                        set_label: "Output Folder:",
                                        set_width_chars: 14,
                                        set_xalign: 0.0,
                                    },

                                    #[name = "output_entry"]
                                    gtk::Entry {
                                        set_hexpand: true,
                                        #[watch]
                                        set_text: &model.settings.paths.output_folder,
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::OutputFolderChanged(entry.text().to_string()));
                                        },
                                    },

                                    gtk::Button {
                                        set_label: "Browse...",
                                        connect_clicked => SettingsMsg::BrowseOutput,
                                    },
                                },

                                // Temp folder
                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 8,

                                    gtk::Label {
                                        set_label: "Temp Folder:",
                                        set_width_chars: 14,
                                        set_xalign: 0.0,
                                    },

                                    #[name = "temp_entry"]
                                    gtk::Entry {
                                        set_hexpand: true,
                                        #[watch]
                                        set_text: &model.settings.paths.temp_root,
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::TempFolderChanged(entry.text().to_string()));
                                        },
                                    },

                                    gtk::Button {
                                        set_label: "Browse...",
                                        connect_clicked => SettingsMsg::BrowseTemp,
                                    },
                                },

                                // Logs folder
                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 8,

                                    gtk::Label {
                                        set_label: "Logs Folder:",
                                        set_width_chars: 14,
                                        set_xalign: 0.0,
                                    },

                                    #[name = "logs_entry"]
                                    gtk::Entry {
                                        set_hexpand: true,
                                        #[watch]
                                        set_text: &model.settings.paths.logs_folder,
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::LogsFolderChanged(entry.text().to_string()));
                                        },
                                    },

                                    gtk::Button {
                                        set_label: "Browse...",
                                        connect_clicked => SettingsMsg::BrowseLogs,
                                    },
                                },
                            },
                        },

                        add_titled[Some("analysis"), "Analysis"] = &gtk::ScrolledWindow {
                            set_vexpand: true,
                            set_hexpand: true,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Vertical,
                                set_spacing: 12,
                                set_margin_all: 16,

                                gtk::Label {
                                    set_label: "Analysis Settings",
                                    set_xalign: 0.0,
                                    add_css_class: "title-3",
                                },

                                // Chunk settings
                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 16,

                                    gtk::Label {
                                        set_label: "Chunk Count:",
                                    },
                                    #[name = "chunk_count_entry"]
                                    gtk::Entry {
                                        set_width_chars: 6,
                                        #[watch]
                                        set_text: &model.settings.analysis.chunk_count.to_string(),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::ChunkCountChanged(entry.text().to_string()));
                                        },
                                    },

                                    gtk::Label {
                                        set_label: "Chunk Duration (s):",
                                    },
                                    #[name = "chunk_duration_entry"]
                                    gtk::Entry {
                                        set_width_chars: 6,
                                        #[watch]
                                        set_text: &model.settings.analysis.chunk_duration.to_string(),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::ChunkDurationChanged(entry.text().to_string()));
                                        },
                                    },
                                },

                                // Min match percentage
                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 8,

                                    gtk::Label {
                                        set_label: "Min Match %:",
                                        set_width_chars: 14,
                                        set_xalign: 0.0,
                                    },
                                    #[name = "min_match_entry"]
                                    gtk::Entry {
                                        set_width_chars: 8,
                                        #[watch]
                                        set_text: &format!("{:.1}", model.settings.analysis.min_match_pct),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::MinMatchPctChanged(entry.text().to_string()));
                                        },
                                    },
                                },

                                // Scan range
                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 16,

                                    gtk::Label {
                                        set_label: "Scan Start %:",
                                    },
                                    #[name = "scan_start_entry"]
                                    gtk::Entry {
                                        set_width_chars: 6,
                                        #[watch]
                                        set_text: &format!("{:.1}", model.settings.analysis.scan_start_pct),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::ScanStartChanged(entry.text().to_string()));
                                        },
                                    },

                                    gtk::Label {
                                        set_label: "Scan End %:",
                                    },
                                    #[name = "scan_end_entry"]
                                    gtk::Entry {
                                        set_width_chars: 6,
                                        #[watch]
                                        set_text: &format!("{:.1}", model.settings.analysis.scan_end_pct),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::ScanEndChanged(entry.text().to_string()));
                                        },
                                    },
                                },

                                gtk::Separator {},

                                // Language filters
                                gtk::Label {
                                    set_label: "Audio Language Filters",
                                    set_xalign: 0.0,
                                    add_css_class: "title-4",
                                },

                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 16,

                                    gtk::Label {
                                        set_label: "Source 1:",
                                    },
                                    #[name = "lang1_entry"]
                                    gtk::Entry {
                                        set_width_chars: 8,
                                        set_placeholder_text: Some("e.g. jpn"),
                                        #[watch]
                                        set_text: model.settings.analysis.lang_source1.as_deref().unwrap_or(""),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::LangSource1Changed(entry.text().to_string()));
                                        },
                                    },

                                    gtk::Label {
                                        set_label: "Others:",
                                    },
                                    #[name = "lang_others_entry"]
                                    gtk::Entry {
                                        set_width_chars: 8,
                                        set_placeholder_text: Some("e.g. eng"),
                                        #[watch]
                                        set_text: model.settings.analysis.lang_others.as_deref().unwrap_or(""),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::LangOthersChanged(entry.text().to_string()));
                                        },
                                    },
                                },

                                gtk::Separator {},

                                // Audio filtering
                                gtk::Label {
                                    set_label: "Audio Filtering",
                                    set_xalign: 0.0,
                                    add_css_class: "title-4",
                                },

                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 16,

                                    gtk::Label {
                                        set_label: "Low Cutoff (Hz):",
                                    },
                                    #[name = "filter_low_entry"]
                                    gtk::Entry {
                                        set_width_chars: 8,
                                        #[watch]
                                        set_text: &format!("{:.0}", model.settings.analysis.filter_low_cutoff_hz),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::FilterLowChanged(entry.text().to_string()));
                                        },
                                    },

                                    gtk::Label {
                                        set_label: "High Cutoff (Hz):",
                                    },
                                    #[name = "filter_high_entry"]
                                    gtk::Entry {
                                        set_width_chars: 8,
                                        #[watch]
                                        set_text: &format!("{:.0}", model.settings.analysis.filter_high_cutoff_hz),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::FilterHighChanged(entry.text().to_string()));
                                        },
                                    },
                                },

                                gtk::CheckButton {
                                    set_label: Some("Use SOXR high-quality resampling"),
                                    #[watch]
                                    set_active: model.settings.analysis.use_soxr,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::UseSoxrChanged(btn.is_active()));
                                    },
                                },

                                gtk::CheckButton {
                                    set_label: Some("Peak fitting (sub-sample accuracy)"),
                                    #[watch]
                                    set_active: model.settings.analysis.audio_peak_fit,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::AudioPeakFitChanged(btn.is_active()));
                                    },
                                },
                            },
                        },

                        add_titled[Some("delay"), "Delay Selection"] = &gtk::ScrolledWindow {
                            set_vexpand: true,
                            set_hexpand: true,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Vertical,
                                set_spacing: 12,
                                set_margin_all: 16,

                                gtk::Label {
                                    set_label: "Delay Selection",
                                    set_xalign: 0.0,
                                    add_css_class: "title-3",
                                },

                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 8,

                                    gtk::Label {
                                        set_label: "Min Accepted Chunks:",
                                        set_width_chars: 20,
                                        set_xalign: 0.0,
                                    },
                                    #[name = "min_chunks_entry"]
                                    gtk::Entry {
                                        set_width_chars: 6,
                                        #[watch]
                                        set_text: &model.settings.analysis.min_accepted_chunks.to_string(),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::MinAcceptedChunksChanged(entry.text().to_string()));
                                        },
                                    },
                                },

                                gtk::Separator {},

                                gtk::Label {
                                    set_label: "First Stable Mode Settings",
                                    set_xalign: 0.0,
                                    add_css_class: "title-4",
                                },

                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 8,

                                    gtk::Label {
                                        set_label: "Min Consecutive Chunks:",
                                        set_width_chars: 20,
                                        set_xalign: 0.0,
                                    },
                                    gtk::Entry {
                                        set_width_chars: 6,
                                        #[watch]
                                        set_text: &model.settings.analysis.first_stable_min_chunks.to_string(),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::FirstStableMinChunksChanged(entry.text().to_string()));
                                        },
                                    },
                                },

                                gtk::CheckButton {
                                    set_label: Some("Skip segments below threshold"),
                                    #[watch]
                                    set_active: model.settings.analysis.first_stable_skip_unstable,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::FirstStableSkipChanged(btn.is_active()));
                                    },
                                },

                                gtk::Separator {},

                                gtk::Label {
                                    set_label: "Early Cluster Settings",
                                    set_xalign: 0.0,
                                    add_css_class: "title-4",
                                },

                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 16,

                                    gtk::Label {
                                        set_label: "Window Size:",
                                    },
                                    gtk::Entry {
                                        set_width_chars: 6,
                                        #[watch]
                                        set_text: &model.settings.analysis.early_cluster_window.to_string(),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::EarlyClusterWindowChanged(entry.text().to_string()));
                                        },
                                    },

                                    gtk::Label {
                                        set_label: "Threshold:",
                                    },
                                    gtk::Entry {
                                        set_width_chars: 6,
                                        #[watch]
                                        set_text: &model.settings.analysis.early_cluster_threshold.to_string(),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::EarlyClusterThresholdChanged(entry.text().to_string()));
                                        },
                                    },
                                },
                            },
                        },

                        add_titled[Some("chapters"), "Chapters"] = &gtk::ScrolledWindow {
                            set_vexpand: true,
                            set_hexpand: true,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Vertical,
                                set_spacing: 12,
                                set_margin_all: 16,

                                gtk::Label {
                                    set_label: "Chapter Settings",
                                    set_xalign: 0.0,
                                    add_css_class: "title-3",
                                },

                                gtk::CheckButton {
                                    set_label: Some("Rename chapters"),
                                    #[watch]
                                    set_active: model.settings.chapters.rename,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::ChapterRenameChanged(btn.is_active()));
                                    },
                                },

                                gtk::Separator {},

                                gtk::Label {
                                    set_label: "Keyframe Snapping",
                                    set_xalign: 0.0,
                                    add_css_class: "title-4",
                                },

                                gtk::CheckButton {
                                    set_label: Some("Snap chapters to keyframes"),
                                    #[watch]
                                    set_active: model.settings.chapters.snap_enabled,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::ChapterSnapChanged(btn.is_active()));
                                    },
                                },

                                gtk::CheckButton {
                                    set_label: Some("Snap starts only (not ends)"),
                                    #[watch]
                                    set_active: model.settings.chapters.snap_starts_only,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::SnapStartsOnlyChanged(btn.is_active()));
                                    },
                                },

                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 8,

                                    gtk::Label {
                                        set_label: "Snap Threshold (ms):",
                                        set_width_chars: 18,
                                        set_xalign: 0.0,
                                    },
                                    gtk::Entry {
                                        set_width_chars: 8,
                                        #[watch]
                                        set_text: &model.settings.chapters.snap_threshold_ms.to_string(),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::SnapThresholdChanged(entry.text().to_string()));
                                        },
                                    },
                                },
                            },
                        },

                        add_titled[Some("merge"), "Merge Behavior"] = &gtk::ScrolledWindow {
                            set_vexpand: true,
                            set_hexpand: true,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Vertical,
                                set_spacing: 12,
                                set_margin_all: 16,

                                gtk::Label {
                                    set_label: "Merge Behavior",
                                    set_xalign: 0.0,
                                    add_css_class: "title-3",
                                },

                                gtk::CheckButton {
                                    set_label: Some("Disable track stats tags"),
                                    #[watch]
                                    set_active: model.settings.postprocess.disable_track_stats_tags,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::DisableTrackStatsChanged(btn.is_active()));
                                    },
                                },

                                gtk::CheckButton {
                                    set_label: Some("Disable header compression"),
                                    #[watch]
                                    set_active: model.settings.postprocess.disable_header_compression,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::DisableHeaderCompressionChanged(btn.is_active()));
                                    },
                                },

                                gtk::CheckButton {
                                    set_label: Some("Apply dialog normalization"),
                                    #[watch]
                                    set_active: model.settings.postprocess.apply_dialog_norm,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::ApplyDialogNormChanged(btn.is_active()));
                                    },
                                },
                            },
                        },

                        add_titled[Some("logging"), "Logging"] = &gtk::ScrolledWindow {
                            set_vexpand: true,
                            set_hexpand: true,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Vertical,
                                set_spacing: 12,
                                set_margin_all: 16,

                                gtk::Label {
                                    set_label: "Logging Settings",
                                    set_xalign: 0.0,
                                    add_css_class: "title-3",
                                },

                                gtk::CheckButton {
                                    set_label: Some("Compact logging"),
                                    #[watch]
                                    set_active: model.settings.logging.compact,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::CompactLoggingChanged(btn.is_active()));
                                    },
                                },

                                gtk::CheckButton {
                                    set_label: Some("Autoscroll"),
                                    #[watch]
                                    set_active: model.settings.logging.autoscroll,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::AutoscrollChanged(btn.is_active()));
                                    },
                                },

                                gtk::Box {
                                    set_orientation: gtk::Orientation::Horizontal,
                                    set_spacing: 16,

                                    gtk::Label {
                                        set_label: "Error tail lines:",
                                    },
                                    gtk::Entry {
                                        set_width_chars: 6,
                                        #[watch]
                                        set_text: &model.settings.logging.error_tail.to_string(),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::ErrorTailChanged(entry.text().to_string()));
                                        },
                                    },

                                    gtk::Label {
                                        set_label: "Progress step %:",
                                    },
                                    gtk::Entry {
                                        set_width_chars: 6,
                                        #[watch]
                                        set_text: &model.settings.logging.progress_step.to_string(),
                                        connect_changed[sender] => move |entry| {
                                            sender.input(SettingsMsg::ProgressStepChanged(entry.text().to_string()));
                                        },
                                    },
                                },

                                gtk::Separator {},

                                gtk::Label {
                                    set_label: "Debug Output",
                                    set_xalign: 0.0,
                                    add_css_class: "title-4",
                                },

                                gtk::CheckButton {
                                    set_label: Some("Show mkvmerge options (pretty)"),
                                    #[watch]
                                    set_active: model.settings.logging.show_options_pretty,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::ShowOptionsPrettyChanged(btn.is_active()));
                                    },
                                },

                                gtk::CheckButton {
                                    set_label: Some("Show mkvmerge options (JSON)"),
                                    #[watch]
                                    set_active: model.settings.logging.show_options_json,
                                    connect_toggled[sender] => move |btn| {
                                        sender.input(SettingsMsg::ShowOptionsJsonChanged(btn.is_active()));
                                    },
                                },
                            },
                        },
                    },

                    // Tab switcher
                    adw::ViewSwitcher {
                        set_stack: Some(&stack),
                        set_policy: adw::ViewSwitcherPolicy::Wide,
                    },

                    // Button row
                    gtk::Box {
                        set_orientation: gtk::Orientation::Horizontal,
                        set_spacing: 8,
                        set_halign: gtk::Align::End,

                        gtk::Button {
                            set_label: "Cancel",
                            connect_clicked => SettingsMsg::Cancel,
                        },

                        gtk::Button {
                            set_label: "Save",
                            add_css_class: "suggested-action",
                            connect_clicked => SettingsMsg::Save,
                        },
                    },
                },
            },
        }
    }

    fn init(
        init: Self::Init,
        root: Self::Root,
        sender: ComponentSender<Self>,
    ) -> ComponentParts<Self> {
        let model = SettingsDialog {
            settings: init,
            active_tab: 0,
        };

        let widgets = view_output!();

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, root: &Self::Root) {
        match msg {
            SettingsMsg::SwitchTab(tab) => {
                self.active_tab = tab;
            }

            // Storage
            SettingsMsg::OutputFolderChanged(s) => self.settings.paths.output_folder = s,
            SettingsMsg::TempFolderChanged(s) => self.settings.paths.temp_root = s,
            SettingsMsg::LogsFolderChanged(s) => self.settings.paths.logs_folder = s,

            SettingsMsg::BrowseOutput => {
                self.browse_folder(root, FolderType::Output, sender.clone());
            }
            SettingsMsg::BrowseTemp => {
                self.browse_folder(root, FolderType::Temp, sender.clone());
            }
            SettingsMsg::BrowseLogs => {
                self.browse_folder(root, FolderType::Logs, sender.clone());
            }

            SettingsMsg::FolderSelected(folder_type, path) => {
                if let Some(p) = path {
                    let path_str = p.to_string_lossy().to_string();
                    match folder_type {
                        FolderType::Output => self.settings.paths.output_folder = path_str,
                        FolderType::Temp => self.settings.paths.temp_root = path_str,
                        FolderType::Logs => self.settings.paths.logs_folder = path_str,
                    }
                }
            }

            // Analysis
            SettingsMsg::AnalysisModeChanged(_idx) => {}
            SettingsMsg::CorrelationMethodChanged(_idx) => {}
            SettingsMsg::SyncModeChanged(_idx) => {}
            SettingsMsg::ChunkCountChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.analysis.chunk_count = v;
                }
            }
            SettingsMsg::ChunkDurationChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.analysis.chunk_duration = v;
                }
            }
            SettingsMsg::MinMatchPctChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.analysis.min_match_pct = v;
                }
            }
            SettingsMsg::ScanStartChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.analysis.scan_start_pct = v;
                }
            }
            SettingsMsg::ScanEndChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.analysis.scan_end_pct = v;
                }
            }
            SettingsMsg::FilteringMethodChanged(_idx) => {}
            SettingsMsg::FilterLowChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.analysis.filter_low_cutoff_hz = v;
                }
            }
            SettingsMsg::FilterHighChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.analysis.filter_high_cutoff_hz = v;
                }
            }
            SettingsMsg::UseSoxrChanged(v) => self.settings.analysis.use_soxr = v,
            SettingsMsg::AudioPeakFitChanged(v) => self.settings.analysis.audio_peak_fit = v,
            SettingsMsg::LangSource1Changed(s) => {
                self.settings.analysis.lang_source1 = if s.is_empty() { None } else { Some(s) };
            }
            SettingsMsg::LangOthersChanged(s) => {
                self.settings.analysis.lang_others = if s.is_empty() { None } else { Some(s) };
            }

            // Multi-correlation
            SettingsMsg::MultiCorrEnabledChanged(v) => {
                self.settings.analysis.multi_correlation_enabled = v;
            }
            SettingsMsg::MultiCorrSccChanged(v) => self.settings.analysis.multi_corr_scc = v,
            SettingsMsg::MultiCorrPhatChanged(v) => self.settings.analysis.multi_corr_gcc_phat = v,
            SettingsMsg::MultiCorrScotChanged(v) => self.settings.analysis.multi_corr_gcc_scot = v,
            SettingsMsg::MultiCorrWhitenedChanged(v) => {
                self.settings.analysis.multi_corr_whitened = v;
            }

            // Delay selection
            SettingsMsg::DelayModeChanged(_idx) => {}
            SettingsMsg::MinAcceptedChunksChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.analysis.min_accepted_chunks = v;
                }
            }
            SettingsMsg::FirstStableMinChunksChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.analysis.first_stable_min_chunks = v;
                }
            }
            SettingsMsg::FirstStableSkipChanged(v) => {
                self.settings.analysis.first_stable_skip_unstable = v;
            }
            SettingsMsg::EarlyClusterWindowChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.analysis.early_cluster_window = v;
                }
            }
            SettingsMsg::EarlyClusterThresholdChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.analysis.early_cluster_threshold = v;
                }
            }

            // Chapters
            SettingsMsg::ChapterRenameChanged(v) => self.settings.chapters.rename = v,
            SettingsMsg::ChapterSnapChanged(v) => self.settings.chapters.snap_enabled = v,
            SettingsMsg::SnapModeChanged(_idx) => {}
            SettingsMsg::SnapThresholdChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.chapters.snap_threshold_ms = v;
                }
            }
            SettingsMsg::SnapStartsOnlyChanged(v) => self.settings.chapters.snap_starts_only = v,

            // Merge behavior
            SettingsMsg::DisableTrackStatsChanged(v) => {
                self.settings.postprocess.disable_track_stats_tags = v;
            }
            SettingsMsg::DisableHeaderCompressionChanged(v) => {
                self.settings.postprocess.disable_header_compression = v;
            }
            SettingsMsg::ApplyDialogNormChanged(v) => {
                self.settings.postprocess.apply_dialog_norm = v;
            }

            // Logging
            SettingsMsg::CompactLoggingChanged(v) => self.settings.logging.compact = v,
            SettingsMsg::AutoscrollChanged(v) => self.settings.logging.autoscroll = v,
            SettingsMsg::ErrorTailChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.logging.error_tail = v;
                }
            }
            SettingsMsg::ProgressStepChanged(s) => {
                if let Ok(v) = s.parse() {
                    self.settings.logging.progress_step = v;
                }
            }
            SettingsMsg::ShowOptionsPrettyChanged(v) => {
                self.settings.logging.show_options_pretty = v;
            }
            SettingsMsg::ShowOptionsJsonChanged(v) => self.settings.logging.show_options_json = v,

            // Dialog actions
            SettingsMsg::Save => {
                let _ = sender.output(SettingsOutput::Saved(self.settings.clone()));
                root.close();
            }
            SettingsMsg::Cancel => {
                let _ = sender.output(SettingsOutput::Cancelled);
                root.close();
            }
        }
    }
}

impl SettingsDialog {
    fn browse_folder(
        &self,
        root: &adw::Window,
        folder_type: FolderType,
        sender: ComponentSender<Self>,
    ) {
        let root = root.clone();
        relm4::spawn_local(async move {
            let dialog = gtk::FileDialog::builder()
                .title("Select Folder")
                .modal(true)
                .build();

            if let Ok(file) = dialog.select_folder_future(Some(&root)).await {
                sender.input(SettingsMsg::FolderSelected(folder_type, file.path()));
            }
        });
    }
}
