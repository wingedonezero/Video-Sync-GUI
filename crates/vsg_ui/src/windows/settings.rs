//! Settings dialog component.
//!
//! Multi-tab settings dialog with all configuration options.

use gtk::glib;
use gtk::prelude::*;
use libadwaita::prelude::*;
use relm4::prelude::*;
use relm4::{Component, ComponentParts, ComponentSender};

use vsg_core::config::Settings;
use vsg_core::models::{AnalysisMode, CorrelationMethod, DelaySelectionMode, FilteringMethod, SnapMode, SyncMode};

/// Output messages from the settings dialog.
#[derive(Debug)]
pub enum SettingsOutput {
    Saved(Settings),
    Cancelled,
}

/// Input messages for the settings dialog.
#[derive(Debug)]
pub enum SettingsMsg {
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
    ArchiveLogsChanged(bool),
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
}

/// String lists for dropdowns
const ANALYSIS_MODES: &[&str] = &["Audio Correlation", "VideoDiff"];
const CORRELATION_METHODS: &[&str] = &["SCC", "GCC-PHAT", "GCC-SCOT", "Whitened"];
const FILTERING_METHODS: &[&str] = &["None", "Low Pass", "Band Pass", "High Pass"];
const DELAY_MODES: &[&str] = &["Mode", "Mode Clustered", "Mode Early", "First Stable", "Average"];
const SNAP_MODES: &[&str] = &["Previous", "Nearest", "Next"];
const SYNC_MODES: &[&str] = &["Positive Only", "Allow Negative"];

#[relm4::component(pub)]
impl Component for SettingsDialog {
    type Init = Settings;
    type Input = SettingsMsg;
    type Output = SettingsOutput;
    type CommandOutput = ();

    view! {
        adw::Window {
            set_title: Some("Settings"),
            set_default_width: 750,
            set_default_height: 650,
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
                    set_spacing: 8,
                    set_margin_all: 12,
                    set_vexpand: true,

                    // Tab view using AdwViewStack
                    #[name = "stack"]
                    adw::ViewStack {
                        set_vexpand: true,

                        // Storage Tab
                        add_titled[Some("storage"), "Storage"] = &gtk::ScrolledWindow {
                            set_vexpand: true,

                            adw::PreferencesGroup {
                                set_title: "Storage Paths",
                                set_margin_all: 12,

                                adw::ActionRow {
                                    set_title: "Output Folder",
                                    set_subtitle: "Where merged files are saved",

                                    add_suffix = &gtk::Entry {
                                        set_hexpand: true,
                                        set_valign: gtk::Align::Center,
                                        #[watch]
                                        set_text: &model.settings.paths.output_folder,
                                        connect_changed[sender] => move |e| {
                                            sender.input(SettingsMsg::OutputFolderChanged(e.text().to_string()));
                                        },
                                    },

                                    add_suffix = &gtk::Button {
                                        set_label: "Browse",
                                        set_valign: gtk::Align::Center,
                                        connect_clicked => SettingsMsg::BrowseOutput,
                                    },
                                },

                                adw::ActionRow {
                                    set_title: "Temp Folder",
                                    set_subtitle: "For temporary processing files",

                                    add_suffix = &gtk::Entry {
                                        set_hexpand: true,
                                        set_valign: gtk::Align::Center,
                                        #[watch]
                                        set_text: &model.settings.paths.temp_root,
                                        connect_changed[sender] => move |e| {
                                            sender.input(SettingsMsg::TempFolderChanged(e.text().to_string()));
                                        },
                                    },

                                    add_suffix = &gtk::Button {
                                        set_label: "Browse",
                                        set_valign: gtk::Align::Center,
                                        connect_clicked => SettingsMsg::BrowseTemp,
                                    },
                                },

                                adw::ActionRow {
                                    set_title: "Logs Folder",
                                    set_subtitle: "Where log files are stored",

                                    add_suffix = &gtk::Entry {
                                        set_hexpand: true,
                                        set_valign: gtk::Align::Center,
                                        #[watch]
                                        set_text: &model.settings.paths.logs_folder,
                                        connect_changed[sender] => move |e| {
                                            sender.input(SettingsMsg::LogsFolderChanged(e.text().to_string()));
                                        },
                                    },

                                    add_suffix = &gtk::Button {
                                        set_label: "Browse",
                                        set_valign: gtk::Align::Center,
                                        connect_clicked => SettingsMsg::BrowseLogs,
                                    },
                                },
                            },
                        },

                        // Analysis Tab
                        add_titled[Some("analysis"), "Analysis"] = &gtk::ScrolledWindow {
                            set_vexpand: true,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Vertical,
                                set_spacing: 12,
                                set_margin_all: 12,

                                adw::PreferencesGroup {
                                    set_title: "Analysis Mode",

                                    adw::ComboRow {
                                        set_title: "Mode",
                                        set_model: Some(&gtk::StringList::new(ANALYSIS_MODES)),
                                        set_selected: model.settings.analysis.mode.to_index() as u32,
                                        connect_selected_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::AnalysisModeChanged(row.selected()));
                                        },
                                    },

                                    adw::ComboRow {
                                        set_title: "Correlation Method",
                                        set_model: Some(&gtk::StringList::new(CORRELATION_METHODS)),
                                        set_selected: model.settings.analysis.correlation_method.to_index() as u32,
                                        connect_selected_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::CorrelationMethodChanged(row.selected()));
                                        },
                                    },

                                    adw::ComboRow {
                                        set_title: "Sync Mode",
                                        set_subtitle: "How to handle negative delays",
                                        set_model: Some(&gtk::StringList::new(SYNC_MODES)),
                                        set_selected: model.settings.analysis.sync_mode.to_index() as u32,
                                        connect_selected_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::SyncModeChanged(row.selected()));
                                        },
                                    },
                                },

                                adw::PreferencesGroup {
                                    set_title: "Language Filters",

                                    adw::EntryRow {
                                        set_title: "Source 1 Language",
                                        #[watch]
                                        set_text: model.settings.analysis.lang_source1.as_deref().unwrap_or(""),
                                        connect_changed[sender] => move |e| {
                                            sender.input(SettingsMsg::LangSource1Changed(e.text().to_string()));
                                        },
                                    },

                                    adw::EntryRow {
                                        set_title: "Other Sources Language",
                                        #[watch]
                                        set_text: model.settings.analysis.lang_others.as_deref().unwrap_or(""),
                                        connect_changed[sender] => move |e| {
                                            sender.input(SettingsMsg::LangOthersChanged(e.text().to_string()));
                                        },
                                    },
                                },

                                adw::PreferencesGroup {
                                    set_title: "Chunk Settings",

                                    adw::SpinRow {
                                        set_title: "Chunk Count",
                                        set_subtitle: "Number of chunks to analyze",
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.analysis.chunk_count as f64,
                                            1.0, 100.0, 1.0, 5.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::ChunkCountChanged(row.value().to_string()));
                                        },
                                    },

                                    adw::SpinRow {
                                        set_title: "Chunk Duration (s)",
                                        set_subtitle: "Length of each chunk in seconds",
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.analysis.chunk_duration as f64,
                                            5.0, 60.0, 1.0, 5.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::ChunkDurationChanged(row.value().to_string()));
                                        },
                                    },

                                    adw::SpinRow {
                                        set_title: "Min Match %",
                                        set_subtitle: "Minimum correlation strength",
                                        set_digits: 1,
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.analysis.min_match_pct,
                                            0.0, 100.0, 0.5, 5.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::MinMatchPctChanged(row.value().to_string()));
                                        },
                                    },

                                    adw::SpinRow {
                                        set_title: "Scan Start %",
                                        set_digits: 1,
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.analysis.scan_start_pct,
                                            0.0, 50.0, 1.0, 5.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::ScanStartChanged(row.value().to_string()));
                                        },
                                    },

                                    adw::SpinRow {
                                        set_title: "Scan End %",
                                        set_digits: 1,
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.analysis.scan_end_pct,
                                            50.0, 100.0, 1.0, 5.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::ScanEndChanged(row.value().to_string()));
                                        },
                                    },
                                },

                                adw::PreferencesGroup {
                                    set_title: "Audio Filtering",

                                    adw::ComboRow {
                                        set_title: "Filtering Method",
                                        set_model: Some(&gtk::StringList::new(FILTERING_METHODS)),
                                        set_selected: model.settings.analysis.filtering_method.to_index() as u32,
                                        connect_selected_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::FilteringMethodChanged(row.selected()));
                                        },
                                    },

                                    adw::SpinRow {
                                        set_title: "Low Cutoff (Hz)",
                                        set_digits: 0,
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.analysis.filter_low_cutoff_hz,
                                            20.0, 2000.0, 10.0, 100.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::FilterLowChanged(row.value().to_string()));
                                        },
                                    },

                                    adw::SpinRow {
                                        set_title: "High Cutoff (Hz)",
                                        set_digits: 0,
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.analysis.filter_high_cutoff_hz,
                                            1000.0, 20000.0, 100.0, 500.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::FilterHighChanged(row.value().to_string()));
                                        },
                                    },

                                    adw::SwitchRow {
                                        set_title: "Use SOXR Resampling",
                                        set_subtitle: "High-quality resampling via FFmpeg",
                                        set_active: model.settings.analysis.use_soxr,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::UseSoxrChanged(row.is_active()));
                                        },
                                    },

                                    adw::SwitchRow {
                                        set_title: "Peak Fitting",
                                        set_subtitle: "Sub-sample accuracy via quadratic interpolation",
                                        set_active: model.settings.analysis.audio_peak_fit,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::AudioPeakFitChanged(row.is_active()));
                                        },
                                    },
                                },

                                adw::PreferencesGroup {
                                    set_title: "Multi-Correlation (Analyze Only)",

                                    adw::SwitchRow {
                                        set_title: "Enable Multi-Correlation",
                                        set_subtitle: "Compare multiple correlation methods",
                                        set_active: model.settings.analysis.multi_correlation_enabled,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::MultiCorrEnabledChanged(row.is_active()));
                                        },
                                    },

                                    adw::SwitchRow {
                                        set_title: "SCC",
                                        set_active: model.settings.analysis.multi_corr_scc,
                                        set_sensitive: model.settings.analysis.multi_correlation_enabled,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::MultiCorrSccChanged(row.is_active()));
                                        },
                                    },

                                    adw::SwitchRow {
                                        set_title: "GCC-PHAT",
                                        set_active: model.settings.analysis.multi_corr_gcc_phat,
                                        set_sensitive: model.settings.analysis.multi_correlation_enabled,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::MultiCorrPhatChanged(row.is_active()));
                                        },
                                    },

                                    adw::SwitchRow {
                                        set_title: "GCC-SCOT",
                                        set_active: model.settings.analysis.multi_corr_gcc_scot,
                                        set_sensitive: model.settings.analysis.multi_correlation_enabled,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::MultiCorrScotChanged(row.is_active()));
                                        },
                                    },

                                    adw::SwitchRow {
                                        set_title: "Whitened",
                                        set_active: model.settings.analysis.multi_corr_whitened,
                                        set_sensitive: model.settings.analysis.multi_correlation_enabled,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::MultiCorrWhitenedChanged(row.is_active()));
                                        },
                                    },
                                },
                            },
                        },

                        // Delay Selection Tab
                        add_titled[Some("delay"), "Delay Selection"] = &gtk::ScrolledWindow {
                            set_vexpand: true,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Vertical,
                                set_spacing: 12,
                                set_margin_all: 12,

                                adw::PreferencesGroup {
                                    set_title: "Delay Selection",

                                    adw::ComboRow {
                                        set_title: "Selection Mode",
                                        set_subtitle: "How to pick final delay from chunks",
                                        set_model: Some(&gtk::StringList::new(DELAY_MODES)),
                                        set_selected: model.settings.analysis.delay_selection_mode.to_index() as u32,
                                        connect_selected_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::DelayModeChanged(row.selected()));
                                        },
                                    },

                                    adw::SpinRow {
                                        set_title: "Min Accepted Chunks",
                                        set_subtitle: "Minimum chunks needed for valid result",
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.analysis.min_accepted_chunks as f64,
                                            1.0, 20.0, 1.0, 1.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::MinAcceptedChunksChanged(row.value().to_string()));
                                        },
                                    },
                                },

                                adw::PreferencesGroup {
                                    set_title: "First Stable Mode Settings",

                                    adw::SpinRow {
                                        set_title: "Min Consecutive Chunks",
                                        set_subtitle: "Chunks with same delay for stability",
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.analysis.first_stable_min_chunks as f64,
                                            1.0, 20.0, 1.0, 1.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::FirstStableMinChunksChanged(row.value().to_string()));
                                        },
                                    },

                                    adw::SwitchRow {
                                        set_title: "Skip Unstable Segments",
                                        set_subtitle: "Skip segments below threshold",
                                        set_active: model.settings.analysis.first_stable_skip_unstable,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::FirstStableSkipChanged(row.is_active()));
                                        },
                                    },
                                },

                                adw::PreferencesGroup {
                                    set_title: "Early Cluster Settings",

                                    adw::SpinRow {
                                        set_title: "Window Size",
                                        set_subtitle: "Early chunks to check for stability",
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.analysis.early_cluster_window as f64,
                                            1.0, 50.0, 1.0, 5.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::EarlyClusterWindowChanged(row.value().to_string()));
                                        },
                                    },

                                    adw::SpinRow {
                                        set_title: "Threshold",
                                        set_subtitle: "Min chunks in early window",
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.analysis.early_cluster_threshold as f64,
                                            1.0, 20.0, 1.0, 1.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::EarlyClusterThresholdChanged(row.value().to_string()));
                                        },
                                    },
                                },
                            },
                        },

                        // Chapters Tab
                        add_titled[Some("chapters"), "Chapters"] = &gtk::ScrolledWindow {
                            set_vexpand: true,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Vertical,
                                set_spacing: 12,
                                set_margin_all: 12,

                                adw::PreferencesGroup {
                                    set_title: "Chapter Settings",

                                    adw::SwitchRow {
                                        set_title: "Rename Chapters",
                                        set_subtitle: "Rename chapters to 'Chapter 1', 'Chapter 2', etc.",
                                        set_active: model.settings.chapters.rename,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::ChapterRenameChanged(row.is_active()));
                                        },
                                    },
                                },

                                adw::PreferencesGroup {
                                    set_title: "Keyframe Snapping",

                                    adw::SwitchRow {
                                        set_title: "Snap to Keyframes",
                                        set_subtitle: "Adjust chapter times to nearest keyframe",
                                        set_active: model.settings.chapters.snap_enabled,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::ChapterSnapChanged(row.is_active()));
                                        },
                                    },

                                    adw::ComboRow {
                                        set_title: "Snap Mode",
                                        set_model: Some(&gtk::StringList::new(SNAP_MODES)),
                                        set_selected: model.settings.chapters.snap_mode.to_index() as u32,
                                        set_sensitive: model.settings.chapters.snap_enabled,
                                        connect_selected_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::SnapModeChanged(row.selected()));
                                        },
                                    },

                                    adw::SpinRow {
                                        set_title: "Snap Threshold (ms)",
                                        set_subtitle: "Maximum distance to snap",
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.chapters.snap_threshold_ms as f64,
                                            50.0, 2000.0, 50.0, 100.0, 0.0
                                        ),
                                        set_sensitive: model.settings.chapters.snap_enabled,
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::SnapThresholdChanged(row.value().to_string()));
                                        },
                                    },

                                    adw::SwitchRow {
                                        set_title: "Snap Starts Only",
                                        set_subtitle: "Only snap chapter start times, not ends",
                                        set_active: model.settings.chapters.snap_starts_only,
                                        set_sensitive: model.settings.chapters.snap_enabled,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::SnapStartsOnlyChanged(row.is_active()));
                                        },
                                    },
                                },
                            },
                        },

                        // Merge Behavior Tab
                        add_titled[Some("merge"), "Merge"] = &gtk::ScrolledWindow {
                            set_vexpand: true,

                            adw::PreferencesGroup {
                                set_title: "Merge Behavior",
                                set_margin_all: 12,

                                adw::SwitchRow {
                                    set_title: "Disable Track Stats Tags",
                                    set_subtitle: "Don't write statistics tags to output",
                                    set_active: model.settings.postprocess.disable_track_stats_tags,
                                    connect_active_notify[sender] => move |row| {
                                        sender.input(SettingsMsg::DisableTrackStatsChanged(row.is_active()));
                                    },
                                },

                                adw::SwitchRow {
                                    set_title: "Disable Header Compression",
                                    set_subtitle: "Improves compatibility with some players",
                                    set_active: model.settings.postprocess.disable_header_compression,
                                    connect_active_notify[sender] => move |row| {
                                        sender.input(SettingsMsg::DisableHeaderCompressionChanged(row.is_active()));
                                    },
                                },

                                adw::SwitchRow {
                                    set_title: "Apply Dialog Normalization",
                                    set_subtitle: "Apply dialnorm gain from audio tracks",
                                    set_active: model.settings.postprocess.apply_dialog_norm,
                                    connect_active_notify[sender] => move |row| {
                                        sender.input(SettingsMsg::ApplyDialogNormChanged(row.is_active()));
                                    },
                                },
                            },
                        },

                        // Logging Tab
                        add_titled[Some("logging"), "Logging"] = &gtk::ScrolledWindow {
                            set_vexpand: true,

                            gtk::Box {
                                set_orientation: gtk::Orientation::Vertical,
                                set_spacing: 12,
                                set_margin_all: 12,

                                adw::PreferencesGroup {
                                    set_title: "Logging Settings",

                                    adw::SwitchRow {
                                        set_title: "Compact Logging",
                                        set_subtitle: "Use shorter log format",
                                        set_active: model.settings.logging.compact,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::CompactLoggingChanged(row.is_active()));
                                        },
                                    },

                                    adw::SwitchRow {
                                        set_title: "Autoscroll",
                                        set_subtitle: "Auto-scroll log to bottom",
                                        set_active: model.settings.logging.autoscroll,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::AutoscrollChanged(row.is_active()));
                                        },
                                    },

                                    adw::SwitchRow {
                                        set_title: "Archive Logs",
                                        set_subtitle: "Archive logs to zip after batch completion",
                                        set_active: model.settings.logging.archive_logs,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::ArchiveLogsChanged(row.is_active()));
                                        },
                                    },

                                    adw::SpinRow {
                                        set_title: "Error Tail Lines",
                                        set_subtitle: "Lines to show from error output",
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.logging.error_tail as f64,
                                            5.0, 100.0, 5.0, 10.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::ErrorTailChanged(row.value().to_string()));
                                        },
                                    },

                                    adw::SpinRow {
                                        set_title: "Progress Step %",
                                        set_subtitle: "How often to report progress",
                                        #[wrap(Some)]
                                        set_adjustment = &gtk::Adjustment::new(
                                            model.settings.logging.progress_step as f64,
                                            5.0, 50.0, 5.0, 10.0, 0.0
                                        ),
                                        connect_value_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::ProgressStepChanged(row.value().to_string()));
                                        },
                                    },
                                },

                                adw::PreferencesGroup {
                                    set_title: "Debug Output",

                                    adw::SwitchRow {
                                        set_title: "Show Options (Pretty)",
                                        set_subtitle: "Log mkvmerge options in readable format",
                                        set_active: model.settings.logging.show_options_pretty,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::ShowOptionsPrettyChanged(row.is_active()));
                                        },
                                    },

                                    adw::SwitchRow {
                                        set_title: "Show Options (JSON)",
                                        set_subtitle: "Log mkvmerge options as raw JSON",
                                        set_active: model.settings.logging.show_options_json,
                                        connect_active_notify[sender] => move |row| {
                                            sender.input(SettingsMsg::ShowOptionsJsonChanged(row.is_active()));
                                        },
                                    },
                                },
                            },
                        },
                    },

                    // Tab switcher bar
                    adw::ViewSwitcherBar {
                        set_stack: Some(&stack),
                        set_reveal: true,
                    },

                    // Button row
                    gtk::Box {
                        set_orientation: gtk::Orientation::Horizontal,
                        set_spacing: 8,
                        set_halign: gtk::Align::End,
                        set_margin_top: 8,

                        #[name = "cancel_btn"]
                        gtk::Button {
                            set_label: "Cancel",
                            // Connected manually in init to avoid panic
                        },

                        #[name = "save_btn"]
                        gtk::Button {
                            set_label: "Save",
                            add_css_class: "suggested-action",
                            // Connected manually in init to avoid panic
                        },
                    },
                },
            },
        }
    }

    fn init(
        init: Self::Init,
        _root: Self::Root,
        sender: ComponentSender<Self>,
    ) -> ComponentParts<Self> {
        let model = SettingsDialog { settings: init };
        let widgets = view_output!();

        // Manually connect buttons to avoid panic if component is destroyed
        // Save button - needs to go through message to get current settings
        let input_sender = sender.input_sender().clone();
        widgets.save_btn.connect_clicked(move |_| {
            let _ = input_sender.send(SettingsMsg::Save);
        });

        // Cancel button - sends output directly
        let output_sender = sender.output_sender().clone();
        widgets.cancel_btn.connect_clicked(move |_| {
            let _ = output_sender.send(SettingsOutput::Cancelled);
        });

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, root: &Self::Root) {
        match msg {
            // Storage
            SettingsMsg::OutputFolderChanged(s) => self.settings.paths.output_folder = s,
            SettingsMsg::TempFolderChanged(s) => self.settings.paths.temp_root = s,
            SettingsMsg::LogsFolderChanged(s) => self.settings.paths.logs_folder = s,

            SettingsMsg::BrowseOutput => self.browse_folder(root, FolderType::Output, sender.clone()),
            SettingsMsg::BrowseTemp => self.browse_folder(root, FolderType::Temp, sender.clone()),
            SettingsMsg::BrowseLogs => self.browse_folder(root, FolderType::Logs, sender.clone()),

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

            // Analysis - enum dropdowns
            SettingsMsg::AnalysisModeChanged(idx) => {
                self.settings.analysis.mode = AnalysisMode::from_index(idx as usize);
            }
            SettingsMsg::CorrelationMethodChanged(idx) => {
                self.settings.analysis.correlation_method = CorrelationMethod::from_index(idx as usize);
            }
            SettingsMsg::SyncModeChanged(idx) => {
                self.settings.analysis.sync_mode = SyncMode::from_index(idx as usize);
            }
            SettingsMsg::FilteringMethodChanged(idx) => {
                self.settings.analysis.filtering_method = FilteringMethod::from_index(idx as usize);
            }

            // Analysis - values
            SettingsMsg::ChunkCountChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.analysis.chunk_count = v; }
            }
            SettingsMsg::ChunkDurationChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.analysis.chunk_duration = v; }
            }
            SettingsMsg::MinMatchPctChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.analysis.min_match_pct = v; }
            }
            SettingsMsg::ScanStartChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.analysis.scan_start_pct = v; }
            }
            SettingsMsg::ScanEndChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.analysis.scan_end_pct = v; }
            }
            SettingsMsg::FilterLowChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.analysis.filter_low_cutoff_hz = v; }
            }
            SettingsMsg::FilterHighChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.analysis.filter_high_cutoff_hz = v; }
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
            SettingsMsg::MultiCorrEnabledChanged(v) => self.settings.analysis.multi_correlation_enabled = v,
            SettingsMsg::MultiCorrSccChanged(v) => self.settings.analysis.multi_corr_scc = v,
            SettingsMsg::MultiCorrPhatChanged(v) => self.settings.analysis.multi_corr_gcc_phat = v,
            SettingsMsg::MultiCorrScotChanged(v) => self.settings.analysis.multi_corr_gcc_scot = v,
            SettingsMsg::MultiCorrWhitenedChanged(v) => self.settings.analysis.multi_corr_whitened = v,

            // Delay selection
            SettingsMsg::DelayModeChanged(idx) => {
                self.settings.analysis.delay_selection_mode = DelaySelectionMode::from_index(idx as usize);
            }
            SettingsMsg::MinAcceptedChunksChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.analysis.min_accepted_chunks = v; }
            }
            SettingsMsg::FirstStableMinChunksChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.analysis.first_stable_min_chunks = v; }
            }
            SettingsMsg::FirstStableSkipChanged(v) => self.settings.analysis.first_stable_skip_unstable = v,
            SettingsMsg::EarlyClusterWindowChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.analysis.early_cluster_window = v; }
            }
            SettingsMsg::EarlyClusterThresholdChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.analysis.early_cluster_threshold = v; }
            }

            // Chapters
            SettingsMsg::ChapterRenameChanged(v) => self.settings.chapters.rename = v,
            SettingsMsg::ChapterSnapChanged(v) => self.settings.chapters.snap_enabled = v,
            SettingsMsg::SnapModeChanged(idx) => {
                self.settings.chapters.snap_mode = SnapMode::from_index(idx as usize);
            }
            SettingsMsg::SnapThresholdChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.chapters.snap_threshold_ms = v; }
            }
            SettingsMsg::SnapStartsOnlyChanged(v) => self.settings.chapters.snap_starts_only = v,

            // Merge behavior
            SettingsMsg::DisableTrackStatsChanged(v) => self.settings.postprocess.disable_track_stats_tags = v,
            SettingsMsg::DisableHeaderCompressionChanged(v) => self.settings.postprocess.disable_header_compression = v,
            SettingsMsg::ApplyDialogNormChanged(v) => self.settings.postprocess.apply_dialog_norm = v,

            // Logging
            SettingsMsg::CompactLoggingChanged(v) => self.settings.logging.compact = v,
            SettingsMsg::AutoscrollChanged(v) => self.settings.logging.autoscroll = v,
            SettingsMsg::ArchiveLogsChanged(v) => self.settings.logging.archive_logs = v,
            SettingsMsg::ErrorTailChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.logging.error_tail = v; }
            }
            SettingsMsg::ProgressStepChanged(s) => {
                if let Ok(v) = s.parse() { self.settings.logging.progress_step = v; }
            }
            SettingsMsg::ShowOptionsPrettyChanged(v) => self.settings.logging.show_options_pretty = v,
            SettingsMsg::ShowOptionsJsonChanged(v) => self.settings.logging.show_options_json = v,

            // Dialog actions
            SettingsMsg::Save => {
                // Defer output to avoid panic when controller is dropped while in click handler
                let settings = self.settings.clone();
                let output_sender = sender.output_sender().clone();
                glib::idle_add_local_once(move || {
                    let _ = output_sender.send(SettingsOutput::Saved(settings));
                });
            }
            SettingsMsg::Cancel => {
                // Note: Cancel button is now connected directly in init to avoid panic
                // This handler is kept for completeness but should not be called
            }
        }
    }
}

impl SettingsDialog {
    fn browse_folder(&self, root: &adw::Window, folder_type: FolderType, sender: ComponentSender<Self>) {
        let root = root.clone();
        // Use input_sender which won't panic if component is destroyed
        let input_sender = sender.input_sender().clone();
        relm4::spawn_local(async move {
            let dialog = gtk::FileDialog::builder()
                .title("Select Folder")
                .modal(true)
                .build();

            if let Ok(file) = dialog.select_folder_future(Some(&root)).await {
                let _ = input_sender.send(SettingsMsg::FolderSelected(folder_type, file.path()));
            }
        });
    }
}

// Add helper methods for enums that don't have them
trait EnumIndex {
    fn to_index(&self) -> usize;
    fn from_index(idx: usize) -> Self;
}

impl EnumIndex for AnalysisMode {
    fn to_index(&self) -> usize {
        match self {
            AnalysisMode::AudioCorrelation => 0,
            AnalysisMode::VideoDiff => 1,
        }
    }
    fn from_index(idx: usize) -> Self {
        match idx {
            1 => AnalysisMode::VideoDiff,
            _ => AnalysisMode::AudioCorrelation,
        }
    }
}

impl EnumIndex for FilteringMethod {
    fn to_index(&self) -> usize {
        match self {
            FilteringMethod::None => 0,
            FilteringMethod::LowPass => 1,
            FilteringMethod::BandPass => 2,
            FilteringMethod::HighPass => 3,
        }
    }
    fn from_index(idx: usize) -> Self {
        match idx {
            1 => FilteringMethod::LowPass,
            2 => FilteringMethod::BandPass,
            3 => FilteringMethod::HighPass,
            _ => FilteringMethod::None,
        }
    }
}

impl EnumIndex for SnapMode {
    fn to_index(&self) -> usize {
        match self {
            SnapMode::Previous => 0,
            SnapMode::Nearest => 1,
            SnapMode::Next => 2,
        }
    }
    fn from_index(idx: usize) -> Self {
        match idx {
            1 => SnapMode::Nearest,
            2 => SnapMode::Next,
            _ => SnapMode::Previous,
        }
    }
}
