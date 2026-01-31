//! Main application module for Video Sync GUI.
//!
//! This module contains the core Application component and shared types
//! following the Relm4 component pattern.

use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use gtk::gdk;
use gtk::glib;
use gtk::prelude::*;
use libadwaita::prelude::*;
use relm4::prelude::*;
use relm4::{Component, ComponentParts, ComponentSender};

use vsg_core::analysis::Analyzer;
use vsg_core::config::{ConfigManager, Settings};
use vsg_core::jobs::{JobQueue, JobQueueEntry, LayoutManager};

use crate::components::{
    add_job::{AddJobDialog, AddJobOutput},
    job_queue::{JobQueueDialog, JobQueueOutput},
    manual_selection::{ManualSelectionDialog, ManualSelectionOutput},
    settings::{SettingsDialog, SettingsOutput},
    track_settings::{TrackSettingsDialog, TrackSettingsOutput},
};

/// Language codes matching the picker options.
/// Index 0 = "und", 1 = "eng", 2 = "jpn", etc.
pub const LANGUAGE_CODES: &[&str] = &[
    "und", "eng", "jpn", "spa", "fre", "ger", "ita", "por", "rus", "chi", "kor", "ara",
];

/// Initialization data for the App component.
pub struct AppInit {
    pub config: Arc<Mutex<ConfigManager>>,
    pub job_queue: Arc<Mutex<JobQueue>>,
    pub layouts_dir: PathBuf,
    pub version_info: String,
}

/// State for a source group in manual selection.
#[derive(Debug, Clone)]
pub struct SourceGroupState {
    pub source_key: String,
    pub title: String,
    pub tracks: Vec<TrackWidgetState>,
    pub is_expanded: bool,
}

/// State for a track widget.
#[derive(Debug, Clone)]
pub struct TrackWidgetState {
    pub id: usize,
    pub track_type: String,
    pub codec_id: String,
    pub language: Option<String>,
    pub summary: String,
    pub badges: String,
    pub is_blocked: bool,
}

/// State for a final track in the layout.
#[derive(Debug, Clone)]
pub struct FinalTrackState {
    pub entry_id: uuid::Uuid,
    pub track_id: usize,
    pub source_key: String,
    pub track_type: String,
    pub codec_id: String,
    pub summary: String,
    pub is_default: bool,
    pub is_forced_display: bool,
    pub sync_to_source: String,
    pub original_lang: Option<String>,
    pub custom_lang: Option<String>,
    pub custom_name: Option<String>,
    pub perform_ocr: bool,
    pub convert_to_ass: bool,
    pub rescale: bool,
    pub size_multiplier_pct: i32,
    pub style_patch: Option<String>,
    pub font_replacements: Option<String>,
    pub sync_exclusion_styles: Vec<String>,
    pub sync_exclusion_mode: SyncExclusionMode,
    pub is_generated: bool,
    pub generated_filter_styles: Vec<String>,
    pub generated_from_entry_id: Option<uuid::Uuid>,
}

impl FinalTrackState {
    pub fn new(
        track_id: usize,
        source_key: String,
        track_type: String,
        codec_id: String,
        summary: String,
        original_lang: Option<String>,
    ) -> Self {
        Self {
            entry_id: uuid::Uuid::new_v4(),
            track_id,
            source_key,
            track_type,
            codec_id,
            summary,
            is_default: false,
            is_forced_display: false,
            sync_to_source: "Source 1".to_string(),
            original_lang,
            custom_lang: None,
            custom_name: None,
            perform_ocr: false,
            convert_to_ass: false,
            rescale: false,
            size_multiplier_pct: 100,
            style_patch: None,
            font_replacements: None,
            sync_exclusion_styles: Vec::new(),
            sync_exclusion_mode: SyncExclusionMode::Exclude,
            is_generated: false,
            generated_filter_styles: Vec::new(),
            generated_from_entry_id: None,
        }
    }

    pub fn is_ocr_compatible(&self) -> bool {
        let codec_upper = self.codec_id.to_uppercase();
        codec_upper.contains("VOBSUB") || codec_upper.contains("PGS")
    }

    pub fn is_convert_to_ass_compatible(&self) -> bool {
        self.codec_id.to_uppercase().contains("S_TEXT/UTF8")
    }

    pub fn is_style_editable(&self) -> bool {
        let codec_upper = self.codec_id.to_uppercase();
        codec_upper.contains("S_TEXT/ASS") || codec_upper.contains("S_TEXT/SSA")
    }

    pub fn supports_sync_exclusion(&self) -> bool {
        self.is_style_editable()
    }

    pub fn badges(&self) -> String {
        let mut badges: Vec<String> = Vec::new();

        if self.is_default {
            badges.push("Default".to_string());
        }
        if self.is_forced_display {
            badges.push("Forced".to_string());
        }
        if self.perform_ocr {
            badges.push("OCR".to_string());
        }
        if self.convert_to_ass {
            badges.push("→ASS".to_string());
        }
        if self.rescale {
            badges.push("Rescale".to_string());
        }
        if self.size_multiplier_pct != 100 {
            badges.push("Sized".to_string());
        }
        if self.style_patch.is_some() {
            badges.push("Styled".to_string());
        }
        if self.font_replacements.is_some() {
            badges.push("Fonts".to_string());
        }
        if !self.sync_exclusion_styles.is_empty() {
            badges.push("SyncEx".to_string());
        }
        if self.is_generated {
            badges.push("Generated".to_string());
        }
        if let Some(ref custom_lang) = self.custom_lang {
            let original = self.original_lang.as_deref().unwrap_or("und");
            if custom_lang != original {
                badges.push(format!("Lang: {}", custom_lang));
            }
        }
        if self.custom_name.is_some() {
            badges.push("Named".to_string());
        }

        badges.join(" | ")
    }
}

/// Sync exclusion mode for subtitle tracks.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum SyncExclusionMode {
    #[default]
    Exclude,
    Include,
}

/// State for track settings dialog.
#[derive(Debug, Clone, Default)]
pub struct TrackSettingsState {
    pub track_type: String,
    pub codec_id: String,
    pub selected_language_idx: usize,
    pub custom_lang: Option<String>,
    pub custom_name: Option<String>,
    pub perform_ocr: bool,
    pub convert_to_ass: bool,
    pub rescale: bool,
    pub size_multiplier_pct: i32,
    pub sync_exclusion_styles: Vec<String>,
    pub sync_exclusion_mode: SyncExclusionMode,
}

/// All possible messages the application can receive.
#[derive(Debug)]
pub enum AppMsg {
    // Main Window Actions
    SourcePathChanged(usize, String),
    BrowseSource(usize),
    FileSelected(usize, Option<PathBuf>),
    FileDropped(usize, PathBuf),
    PasteToSource(usize),
    AnalyzeOnly,
    ArchiveLogsChanged(bool),
    AnalysisProgress(f32, String),
    AnalysisComplete {
        delay_source2_ms: Option<i64>,
        delay_source3_ms: Option<i64>,
    },
    AnalysisFailed(String),

    // Window Management
    OpenSettings,
    OpenJobQueue,
    OpenAddJob,
    OpenManualSelection(usize),
    OpenTrackSettings(usize),

    // Dialog Outputs
    SettingsClosed(SettingsOutput),
    JobQueueClosed(JobQueueOutput),
    AddJobClosed(AddJobOutput),
    ManualSelectionClosed(ManualSelectionOutput),
    TrackSettingsClosed(TrackSettingsOutput),

    // Batch Processing
    StartBatchProcessing(Vec<JobQueueEntry>),
    ProcessNextJob,
    ProcessingProgress { job_idx: usize, progress: f32 },
    JobCompleted { job_idx: usize, success: bool, error: Option<String> },
    BatchCompleted,

    // Internal
    Quit,
}

/// Main application state.
pub struct App {
    pub config: Arc<Mutex<ConfigManager>>,
    pub job_queue: Arc<Mutex<JobQueue>>,
    pub layout_manager: Arc<Mutex<LayoutManager>>,

    // Main Window State
    pub source1_path: String,
    pub source2_path: String,
    pub source3_path: String,
    pub archive_logs: bool,
    pub status_text: String,
    pub progress_value: f32,
    pub delay_source2: String,
    pub delay_source3: String,
    pub log_text: String,
    pub is_analyzing: bool,

    // Settings Dialog
    pub settings_dialog: Option<Controller<SettingsDialog>>,
    pub pending_settings: Option<Settings>,

    // Job Queue Dialog
    pub job_queue_dialog: Option<Controller<JobQueueDialog>>,
    pub selected_job_indices: Vec<usize>,
    pub has_clipboard: bool,
    pub is_processing: bool,
    pub job_queue_status: String,

    // Batch Processing State
    pub processing_jobs: Vec<JobQueueEntry>,
    pub current_job_index: usize,
    pub total_jobs: usize,
    pub batch_status: String,

    // Add Job Dialog
    pub add_job_dialog: Option<Controller<AddJobDialog>>,

    // Manual Selection Dialog
    pub manual_selection_dialog: Option<Controller<ManualSelectionDialog>>,
    pub manual_selection_job_idx: Option<usize>,
    pub source_groups: Vec<SourceGroupState>,
    pub final_tracks: Vec<FinalTrackState>,
    pub attachment_sources: std::collections::HashMap<String, bool>,
    pub external_subtitles: Vec<PathBuf>,

    // Track Settings Dialog
    pub track_settings_dialog: Option<Controller<TrackSettingsDialog>>,
    pub track_settings_idx: Option<usize>,
    pub track_settings: TrackSettingsState,
}

impl App {
    pub fn append_log(&mut self, message: &str) {
        self.log_text.push_str(message);
        self.log_text.push('\n');
    }

    pub fn source_keys(&self) -> Vec<String> {
        self.source_groups.iter().map(|g| g.source_key.clone()).collect()
    }
}

/// Setup drag-drop for an entry widget
fn setup_drop_target(entry: &gtk::Entry, source_idx: usize, sender: ComponentSender<App>) {
    let drop_target = gtk::DropTarget::new(gdk::FileList::static_type(), gdk::DragAction::COPY);

    drop_target.connect_drop(move |_target, value, _x, _y| {
        if let Ok(file_list) = value.get::<gdk::FileList>() {
            if let Some(file) = file_list.files().first() {
                if let Some(path) = file.path() {
                    sender.input(AppMsg::FileDropped(source_idx, path));
                    return true;
                }
            }
        }
        false
    });

    entry.add_controller(drop_target);
}

/// Setup clipboard paste for an entry widget
fn setup_paste_handler(entry: &gtk::Entry, source_idx: usize, sender: ComponentSender<App>) {
    let gesture = gtk::GestureClick::new();
    gesture.set_button(0); // Any button

    let key_controller = gtk::EventControllerKey::new();
    let sender_clone = sender.clone();

    key_controller.connect_key_pressed(move |_controller, key, _code, state| {
        // Check for Ctrl+V
        if state.contains(gdk::ModifierType::CONTROL_MASK) && key == gdk::Key::v {
            sender_clone.input(AppMsg::PasteToSource(source_idx));
            return glib::Propagation::Stop;
        }
        glib::Propagation::Proceed
    });

    entry.add_controller(key_controller);
}

#[relm4::component(pub)]
impl Component for App {
    type Init = AppInit;
    type Input = AppMsg;
    type Output = ();
    type CommandOutput = ();

    view! {
        adw::ApplicationWindow {
            set_title: Some("Video Sync GUI"),
            set_default_width: 1200,
            set_default_height: 720,

            #[wrap(Some)]
            set_content = &adw::ToolbarView {
                add_top_bar = &adw::HeaderBar {
                    #[wrap(Some)]
                    set_title_widget = &gtk::Label {
                        set_label: "Video Sync GUI",
                    },
                    pack_start = &gtk::Button {
                        set_label: "Settings...",
                        connect_clicked => AppMsg::OpenSettings,
                    },
                },

                #[wrap(Some)]
                set_content = &gtk::Box {
                    set_orientation: gtk::Orientation::Vertical,
                    set_spacing: 12,
                    set_margin_all: 16,

                    // Archive logs checkbox
                    gtk::CheckButton {
                        set_label: Some("Archive logs to zip on batch completion"),
                        set_active: model.archive_logs,
                        connect_toggled[sender] => move |btn| {
                            sender.input(AppMsg::ArchiveLogsChanged(btn.is_active()));
                        },
                    },

                    // Main Workflow Section
                    gtk::Frame {
                        set_label: Some("Main Workflow"),

                        gtk::Box {
                            set_orientation: gtk::Orientation::Vertical,
                            set_spacing: 8,
                            set_margin_all: 12,

                            gtk::Button {
                                set_label: "Open Job Queue for Merging...",
                                add_css_class: "suggested-action",
                                connect_clicked => AppMsg::OpenJobQueue,
                            },
                        },
                    },

                    // Quick Analysis Section
                    gtk::Frame {
                        set_label: Some("Quick Analysis (Analyze Only)"),

                        gtk::Box {
                            set_orientation: gtk::Orientation::Vertical,
                            set_spacing: 8,
                            set_margin_all: 12,

                            // Source 1
                            gtk::Box {
                                set_orientation: gtk::Orientation::Horizontal,
                                set_spacing: 8,

                                gtk::Label {
                                    set_label: "Source 1 (Reference):",
                                    set_width_chars: 18,
                                    set_xalign: 0.0,
                                },

                                #[name = "source1_entry"]
                                gtk::Entry {
                                    set_hexpand: true,
                                    set_placeholder_text: Some("Drop file or Ctrl+V to paste path..."),
                                    set_text: &model.source1_path,
                                    connect_changed[sender] => move |entry| {
                                        sender.input(AppMsg::SourcePathChanged(1, entry.text().to_string()));
                                    },
                                },

                                gtk::Button {
                                    set_label: "Browse...",
                                    connect_clicked => AppMsg::BrowseSource(1),
                                },
                            },

                            // Source 2
                            gtk::Box {
                                set_orientation: gtk::Orientation::Horizontal,
                                set_spacing: 8,

                                gtk::Label {
                                    set_label: "Source 2:",
                                    set_width_chars: 18,
                                    set_xalign: 0.0,
                                },

                                #[name = "source2_entry"]
                                gtk::Entry {
                                    set_hexpand: true,
                                    set_placeholder_text: Some("Drop file or Ctrl+V to paste path..."),
                                    set_text: &model.source2_path,
                                    connect_changed[sender] => move |entry| {
                                        sender.input(AppMsg::SourcePathChanged(2, entry.text().to_string()));
                                    },
                                },

                                gtk::Button {
                                    set_label: "Browse...",
                                    connect_clicked => AppMsg::BrowseSource(2),
                                },
                            },

                            // Source 3
                            gtk::Box {
                                set_orientation: gtk::Orientation::Horizontal,
                                set_spacing: 8,

                                gtk::Label {
                                    set_label: "Source 3:",
                                    set_width_chars: 18,
                                    set_xalign: 0.0,
                                },

                                #[name = "source3_entry"]
                                gtk::Entry {
                                    set_hexpand: true,
                                    set_placeholder_text: Some("Drop file or Ctrl+V to paste path..."),
                                    set_text: &model.source3_path,
                                    connect_changed[sender] => move |entry| {
                                        sender.input(AppMsg::SourcePathChanged(3, entry.text().to_string()));
                                    },
                                },

                                gtk::Button {
                                    set_label: "Browse...",
                                    connect_clicked => AppMsg::BrowseSource(3),
                                },
                            },

                            // Analyze button
                            gtk::Box {
                                set_orientation: gtk::Orientation::Horizontal,
                                set_halign: gtk::Align::End,

                                gtk::Button {
                                    #[watch]
                                    set_label: if model.is_analyzing { "Analyzing..." } else { "Analyze Only" },
                                    #[watch]
                                    set_sensitive: !model.is_analyzing && !model.source1_path.is_empty() && !model.source2_path.is_empty(),
                                    connect_clicked => AppMsg::AnalyzeOnly,
                                },
                            },
                        },
                    },

                    // Latest Job Results Section
                    gtk::Frame {
                        set_label: Some("Latest Job Results"),

                        gtk::Box {
                            set_orientation: gtk::Orientation::Horizontal,
                            set_spacing: 16,
                            set_margin_all: 12,

                            gtk::Label {
                                set_label: "Source 2 Delay:",
                            },
                            gtk::Label {
                                #[watch]
                                set_label: if model.delay_source2.is_empty() { "-" } else { &model.delay_source2 },
                            },

                            gtk::Label {
                                set_label: "Source 3 Delay:",
                            },
                            gtk::Label {
                                #[watch]
                                set_label: if model.delay_source3.is_empty() { "-" } else { &model.delay_source3 },
                            },
                        },
                    },

                    // Log Section
                    gtk::Frame {
                        set_label: Some("Log"),
                        set_vexpand: true,

                        gtk::ScrolledWindow {
                            set_vexpand: true,
                            set_hexpand: true,
                            set_min_content_height: 200,

                            #[name = "log_view"]
                            gtk::TextView {
                                set_editable: false,
                                set_monospace: true,
                                set_wrap_mode: gtk::WrapMode::None,
                                set_left_margin: 8,
                                set_right_margin: 8,
                                set_top_margin: 8,
                                set_bottom_margin: 8,
                            },
                        },
                    },

                    // Status Bar
                    gtk::Box {
                        set_orientation: gtk::Orientation::Horizontal,
                        set_spacing: 8,

                        gtk::Label {
                            set_label: "Status:",
                        },
                        gtk::Label {
                            #[watch]
                            set_label: &model.status_text,
                            set_hexpand: true,
                            set_xalign: 0.0,
                        },
                        gtk::ProgressBar {
                            set_width_request: 200,
                            #[watch]
                            set_fraction: model.progress_value as f64 / 100.0,
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
        let archive_logs = {
            let cfg = init.config.lock().unwrap();
            cfg.settings().logging.archive_logs
        };
        let layout_manager = Arc::new(Mutex::new(LayoutManager::new(&init.layouts_dir)));

        let model = App {
            config: init.config,
            job_queue: init.job_queue,
            layout_manager,

            source1_path: String::new(),
            source2_path: String::new(),
            source3_path: String::new(),
            archive_logs,
            status_text: "Ready".to_string(),
            progress_value: 0.0,
            delay_source2: String::new(),
            delay_source3: String::new(),
            log_text: init.version_info,
            is_analyzing: false,

            settings_dialog: None,
            pending_settings: None,

            job_queue_dialog: None,
            selected_job_indices: Vec::new(),
            has_clipboard: false,
            is_processing: false,
            job_queue_status: String::new(),

            processing_jobs: Vec::new(),
            current_job_index: 0,
            total_jobs: 0,
            batch_status: String::new(),

            add_job_dialog: None,

            manual_selection_dialog: None,
            manual_selection_job_idx: None,
            source_groups: Vec::new(),
            final_tracks: Vec::new(),
            attachment_sources: std::collections::HashMap::new(),
            external_subtitles: Vec::new(),

            track_settings_dialog: None,
            track_settings_idx: None,
            track_settings: TrackSettingsState::default(),
        };

        let widgets = view_output!();

        // Set initial log text
        widgets.log_view.buffer().set_text(&model.log_text);

        // Setup drag-drop for source entries
        setup_drop_target(&widgets.source1_entry, 1, sender.clone());
        setup_drop_target(&widgets.source2_entry, 2, sender.clone());
        setup_drop_target(&widgets.source3_entry, 3, sender.clone());

        // Setup paste handlers
        setup_paste_handler(&widgets.source1_entry, 1, sender.clone());
        setup_paste_handler(&widgets.source2_entry, 2, sender.clone());
        setup_paste_handler(&widgets.source3_entry, 3, sender.clone());

        ComponentParts { model, widgets }
    }

    fn update(&mut self, msg: Self::Input, sender: ComponentSender<Self>, root: &Self::Root) {
        match msg {
            AppMsg::SourcePathChanged(idx, path) => {
                match idx {
                    1 => self.source1_path = path,
                    2 => self.source2_path = path,
                    3 => self.source3_path = path,
                    _ => {}
                }
            }

            AppMsg::BrowseSource(idx) => {
                let sender = sender.clone();
                let root = root.clone();
                relm4::spawn_local(async move {
                    let dialog = gtk::FileDialog::builder()
                        .title("Select Source File")
                        .modal(true)
                        .build();

                    if let Ok(file) = dialog.open_future(Some(&root)).await {
                        if let Some(path) = file.path() {
                            sender.input(AppMsg::FileSelected(idx, Some(path)));
                        }
                    }
                });
            }

            AppMsg::FileSelected(idx, path) => {
                if let Some(p) = path {
                    let path_str = p.to_string_lossy().to_string();
                    match idx {
                        1 => self.source1_path = path_str,
                        2 => self.source2_path = path_str,
                        3 => self.source3_path = path_str,
                        _ => {}
                    }
                }
            }

            AppMsg::FileDropped(idx, path) => {
                let path_str = path.to_string_lossy().to_string();
                match idx {
                    1 => self.source1_path = path_str,
                    2 => self.source2_path = path_str,
                    3 => self.source3_path = path_str,
                    _ => {}
                }
            }

            AppMsg::PasteToSource(idx) => {
                let sender = sender.clone();
                let display = gdk::Display::default().unwrap();
                let clipboard = display.clipboard();

                relm4::spawn_local(async move {
                    if let Ok(text) = clipboard.read_text_future().await {
                        if let Some(text) = text {
                            let path = text.trim().to_string();
                            // Handle file:// URIs
                            let path = if path.starts_with("file://") {
                                percent_encoding::percent_decode_str(&path[7..])
                                    .decode_utf8_lossy()
                                    .to_string()
                            } else {
                                path
                            };
                            sender.input(AppMsg::SourcePathChanged(idx, path));
                        }
                    }
                });
            }

            AppMsg::AnalyzeOnly => {
                if !self.is_analyzing && !self.source1_path.is_empty() && !self.source2_path.is_empty() {
                    self.is_analyzing = true;
                    self.status_text = "Analyzing...".to_string();
                    self.progress_value = 0.0;
                    self.delay_source2.clear();
                    self.delay_source3.clear();
                    self.append_log("\n--- Starting Analysis ---");

                    let source1 = PathBuf::from(&self.source1_path);
                    let source2 = PathBuf::from(&self.source2_path);
                    let source3 = if self.source3_path.is_empty() {
                        None
                    } else {
                        Some(PathBuf::from(&self.source3_path))
                    };

                    // Get analysis settings
                    let settings = {
                        let cfg = self.config.lock().unwrap();
                        cfg.settings().analysis.clone()
                    };

                    let sender = sender.clone();

                    // Run analysis in background thread
                    std::thread::spawn(move || {
                        let analyzer = Analyzer::from_settings(&settings);

                        sender.input(AppMsg::AnalysisProgress(10.0, "Analyzing Source 2...".to_string()));

                        // Analyze Source 2
                        let delay2 = match analyzer.analyze(&source1, &source2, "Source 2") {
                            Ok(result) => {
                                let delay_ms = result.delay.delay_ms_rounded;
                                sender.input(AppMsg::AnalysisProgress(
                                    50.0,
                                    format!("Source 2: {} ms (match: {:.1}%)", delay_ms, result.avg_match_pct),
                                ));
                                Some(delay_ms)
                            }
                            Err(e) => {
                                sender.input(AppMsg::AnalysisProgress(50.0, format!("Source 2 failed: {}", e)));
                                None
                            }
                        };

                        // Analyze Source 3 if provided
                        let delay3 = if let Some(ref s3) = source3 {
                            sender.input(AppMsg::AnalysisProgress(60.0, "Analyzing Source 3...".to_string()));
                            match analyzer.analyze(&source1, s3, "Source 3") {
                                Ok(result) => {
                                    let delay_ms = result.delay.delay_ms_rounded;
                                    sender.input(AppMsg::AnalysisProgress(
                                        90.0,
                                        format!("Source 3: {} ms (match: {:.1}%)", delay_ms, result.avg_match_pct),
                                    ));
                                    Some(delay_ms)
                                }
                                Err(e) => {
                                    sender.input(AppMsg::AnalysisProgress(90.0, format!("Source 3 failed: {}", e)));
                                    None
                                }
                            }
                        } else {
                            None
                        };

                        if delay2.is_some() || delay3.is_some() {
                            sender.input(AppMsg::AnalysisComplete {
                                delay_source2_ms: delay2,
                                delay_source3_ms: delay3,
                            });
                        } else {
                            sender.input(AppMsg::AnalysisFailed("All sources failed to analyze".to_string()));
                        }
                    });
                }
            }

            AppMsg::ArchiveLogsChanged(value) => {
                self.archive_logs = value;
            }

            AppMsg::AnalysisProgress(progress, message) => {
                self.progress_value = progress;
                self.status_text = message.clone();
                self.append_log(&message);
            }

            AppMsg::AnalysisComplete { delay_source2_ms, delay_source3_ms } => {
                self.is_analyzing = false;
                self.status_text = "Analysis complete".to_string();
                self.progress_value = 100.0;

                if let Some(delay) = delay_source2_ms {
                    self.delay_source2 = format!("{} ms", delay);
                    self.append_log(&format!("✓ Source 2 delay: {} ms", delay));
                }
                if let Some(delay) = delay_source3_ms {
                    self.delay_source3 = format!("{} ms", delay);
                    self.append_log(&format!("✓ Source 3 delay: {} ms", delay));
                }

                self.append_log("--- Analysis Complete ---\n");
            }

            AppMsg::AnalysisFailed(error) => {
                self.is_analyzing = false;
                self.status_text = format!("Analysis failed: {}", error);
                self.progress_value = 0.0;
                self.append_log(&format!("✗ Analysis failed: {}", error));
            }

            AppMsg::OpenSettings => {
                if self.settings_dialog.is_none() {
                    let settings = {
                        let cfg = self.config.lock().unwrap();
                        cfg.settings().clone()
                    };

                    let dialog = SettingsDialog::builder()
                        .transient_for(root)
                        .launch(settings)
                        .forward(sender.input_sender(), |output| {
                            AppMsg::SettingsClosed(output)
                        });

                    dialog.widget().present();
                    self.settings_dialog = Some(dialog);
                }
            }

            AppMsg::SettingsClosed(output) => {
                self.settings_dialog = None;
                if let SettingsOutput::Saved(settings) = output {
                    let save_result = {
                        let mut cfg = self.config.lock().unwrap();
                        *cfg.settings_mut() = settings;
                        cfg.save()
                    };
                    if let Err(e) = save_result {
                        self.append_log(&format!("Failed to save settings: {}", e));
                    } else {
                        self.append_log("Settings saved.");
                    }
                }
            }

            AppMsg::OpenJobQueue => {
                if self.job_queue_dialog.is_none() {
                    let dialog = JobQueueDialog::builder()
                        .transient_for(root)
                        .launch(self.job_queue.clone())
                        .forward(sender.input_sender(), |output| {
                            AppMsg::JobQueueClosed(output)
                        });

                    dialog.widget().present();
                    self.job_queue_dialog = Some(dialog);
                }
            }

            AppMsg::JobQueueClosed(output) => {
                self.job_queue_dialog = None;
                match output {
                    JobQueueOutput::StartProcessing(jobs) => {
                        sender.input(AppMsg::StartBatchProcessing(jobs));
                    }
                    JobQueueOutput::OpenManualSelection(idx) => {
                        sender.input(AppMsg::OpenManualSelection(idx));
                    }
                    JobQueueOutput::Closed => {}
                }
            }

            AppMsg::OpenAddJob => {
                if self.add_job_dialog.is_none() {
                    let dialog = AddJobDialog::builder()
                        .transient_for(root)
                        .launch(self.job_queue.clone())
                        .forward(sender.input_sender(), |output| {
                            AppMsg::AddJobClosed(output)
                        });

                    dialog.widget().present();
                    self.add_job_dialog = Some(dialog);
                }
            }

            AppMsg::AddJobClosed(output) => {
                self.add_job_dialog = None;
                if let AddJobOutput::JobsAdded(count) = output {
                    self.job_queue_status = format!("Added {} job(s)", count);
                }
            }

            AppMsg::OpenManualSelection(idx) => {
                self.manual_selection_job_idx = Some(idx);

                if self.manual_selection_dialog.is_none() {
                    let dialog = ManualSelectionDialog::builder()
                        .transient_for(root)
                        .launch((self.job_queue.clone(), self.layout_manager.clone(), idx))
                        .forward(sender.input_sender(), |output| {
                            AppMsg::ManualSelectionClosed(output)
                        });

                    dialog.widget().present();
                    self.manual_selection_dialog = Some(dialog);
                }
            }

            AppMsg::ManualSelectionClosed(output) => {
                self.manual_selection_dialog = None;
                self.manual_selection_job_idx = None;

                if let ManualSelectionOutput::LayoutAccepted = output {
                    self.job_queue_status = "Layout saved.".to_string();
                }
            }

            AppMsg::OpenTrackSettings(idx) => {
                self.track_settings_idx = Some(idx);

                if self.track_settings_dialog.is_none() {
                    let track = self.final_tracks.get(idx).cloned();

                    if let Some(track) = track {
                        let dialog = TrackSettingsDialog::builder()
                            .transient_for(root)
                            .launch(track)
                            .forward(sender.input_sender(), |output| {
                                AppMsg::TrackSettingsClosed(output)
                            });

                        dialog.widget().present();
                        self.track_settings_dialog = Some(dialog);
                    }
                }
            }

            AppMsg::TrackSettingsClosed(output) => {
                self.track_settings_dialog = None;

                if let TrackSettingsOutput::Accepted(updated_track) = output {
                    if let Some(idx) = self.track_settings_idx {
                        if let Some(track) = self.final_tracks.get_mut(idx) {
                            *track = updated_track;
                        }
                    }
                }

                self.track_settings_idx = None;
            }

            AppMsg::StartBatchProcessing(jobs) => {
                self.processing_jobs = jobs;
                self.total_jobs = self.processing_jobs.len();
                self.current_job_index = 0;
                self.is_processing = true;

                if !self.processing_jobs.is_empty() {
                    sender.input(AppMsg::ProcessNextJob);
                }
            }

            AppMsg::ProcessNextJob => {
                if self.current_job_index < self.total_jobs {
                    self.batch_status = format!(
                        "Processing job {} of {}",
                        self.current_job_index + 1,
                        self.total_jobs
                    );
                    self.append_log(&self.batch_status.clone());

                    // TODO: Implement actual job processing using orchestrator
                    let sender = sender.clone();
                    let job_idx = self.current_job_index;
                    relm4::spawn_local(async move {
                        tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;
                        sender.input(AppMsg::JobCompleted {
                            job_idx,
                            success: true,
                            error: None,
                        });
                    });
                } else {
                    sender.input(AppMsg::BatchCompleted);
                }
            }

            AppMsg::ProcessingProgress { job_idx, progress } => {
                if job_idx == self.current_job_index && self.is_processing {
                    self.progress_value = progress;
                }
            }

            AppMsg::JobCompleted { job_idx, success, error } => {
                if success {
                    self.append_log(&format!("Job {} completed successfully.", job_idx + 1));
                } else if let Some(err) = error {
                    self.append_log(&format!("Job {} failed: {}", job_idx + 1, err));
                }

                self.current_job_index += 1;
                sender.input(AppMsg::ProcessNextJob);
            }

            AppMsg::BatchCompleted => {
                self.is_processing = false;
                self.batch_status = "Batch processing complete.".to_string();
                self.append_log("Batch processing complete.");
                self.status_text = "Ready".to_string();
                self.progress_value = 100.0;
            }

            AppMsg::Quit => {
                relm4::main_application().quit();
            }
        }
    }
}
