//! Main application module for Video Sync GUI.
//!
//! This module contains the core Application struct, Message enum,
//! and the update/view logic following the iced MVU pattern.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use iced::widget::{self, text};
use iced::window;
use iced::{Element, Size, Subscription, Task, Theme};

use vsg_core::config::{ConfigManager, Settings};
use vsg_core::jobs::JobQueue;

use crate::pages;
use crate::windows;

/// Unique identifier for windows.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum WindowKind {
    Main,
    Settings,
    JobQueue,
    AddJob,
    ManualSelection(usize),
    TrackSettings(usize),
}

/// All possible messages the application can receive.
#[derive(Debug, Clone)]
pub enum Message {
    // Window Management
    OpenSettings,
    CloseSettings,
    OpenJobQueue,
    CloseJobQueue,
    OpenAddJob,
    CloseAddJob,
    OpenManualSelection(usize),
    CloseManualSelection,
    OpenTrackSettings(usize),
    CloseTrackSettings,
    WindowClosed(window::Id),
    WindowOpened(WindowKind, window::Id),

    // Main Window
    SourcePathChanged(usize, String),
    BrowseSource(usize),
    FileSelected(usize, Option<PathBuf>),
    AnalyzeOnly,
    ArchiveLogsChanged(bool),
    AnalysisProgress(f32),
    AnalysisLog(String),
    AnalysisComplete {
        delay_source2_ms: Option<i64>,
        delay_source3_ms: Option<i64>,
    },
    AnalysisFailed(String),

    // Settings Window
    SettingChanged(SettingKey, SettingValue),
    SaveSettings,
    CancelSettings,
    BrowseFolder(FolderType),
    FolderSelected(FolderType, Option<PathBuf>),
    SettingsTabSelected(usize),

    // Job Queue Dialog
    AddJobsClicked,
    JobRowSelected(usize, bool),
    JobRowDoubleClicked(usize),
    RemoveSelectedJobs,
    MoveJobsUp,
    MoveJobsDown,
    CopyLayout(usize),
    PasteLayout,
    StartProcessing,
    ProcessingProgress { job_idx: usize, progress: f32 },
    ProcessingComplete,
    ProcessingFailed(String),

    // Add Job Dialog
    AddSource,
    RemoveSource(usize),
    AddJobSourceChanged(usize, String),
    AddJobBrowseSource(usize),
    AddJobFileSelected(usize, Option<PathBuf>),
    FindAndAddJobs,
    JobsAdded(usize),

    // Manual Selection Dialog
    SourceTrackDoubleClicked { track_id: usize, source_key: String },
    FinalTrackMoved(usize, usize),
    FinalTrackRemoved(usize),
    FinalTrackDefaultChanged(usize, bool),
    FinalTrackForcedChanged(usize, bool),
    FinalTrackSyncChanged(usize, String),
    FinalTrackSettingsClicked(usize),
    AttachmentToggled(String, bool),
    AddExternalSubtitles,
    ExternalFilesSelected(Vec<PathBuf>),
    AcceptLayout,

    // Track Settings Dialog
    TrackLanguageChanged(usize),
    TrackCustomNameChanged(String),
    TrackPerformOcrChanged(bool),
    TrackConvertToAssChanged(bool),
    TrackRescaleChanged(bool),
    TrackSizeMultiplierChanged(i32),
    ConfigureSyncExclusion,
    AcceptTrackSettings,

    // Stub Dialogs
    OpenStyleEditor(usize),
    CloseStyleEditor,
    OpenGeneratedTrack,
    CloseGeneratedTrack,
    OpenSyncExclusion,
    CloseSyncExclusion,
    OpenSourceSettings(String),
    CloseSourceSettings,

    // Internal
    Noop,
}

/// Settings keys for type-safe settings updates.
#[derive(Debug, Clone, PartialEq)]
pub enum SettingKey {
    OutputFolder,
    TempRoot,
    LogsFolder,
    CompactLogging,
    Autoscroll,
    ErrorTail,
    ProgressStep,
    ShowOptionsPretty,
    ShowOptionsJson,
    AnalysisMode,
    CorrelationMethod,
    SyncMode,
    LangSource1,
    LangOthers,
    ChunkCount,
    ChunkDuration,
    MinMatchPct,
    ScanStartPct,
    ScanEndPct,
    FilteringMethod,
    FilterLowCutoffHz,
    FilterHighCutoffHz,
    UseSoxr,
    AudioPeakFit,
    MultiCorrelationEnabled,
    MultiCorrScc,
    MultiCorrGccPhat,
    MultiCorrGccScot,
    MultiCorrWhitened,
    DelaySelectionMode,
    MinAcceptedChunks,
    FirstStableMinChunks,
    FirstStableSkipUnstable,
    EarlyClusterWindow,
    EarlyClusterThreshold,
    ChapterRename,
    ChapterSnap,
    SnapMode,
    SnapThresholdMs,
    SnapStartsOnly,
    DisableTrackStats,
    DisableHeaderCompression,
    ApplyDialogNorm,
}

/// Setting values for type-safe settings updates.
#[derive(Debug, Clone)]
pub enum SettingValue {
    String(String),
    Bool(bool),
    I32(i32),
    F32(f32),
}

/// Folder types for browse dialogs.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FolderType {
    Output,
    Temp,
    Logs,
}

/// Main application state.
pub struct App {
    pub config: Arc<Mutex<ConfigManager>>,
    pub job_queue: Arc<Mutex<JobQueue>>,

    // Main Window State
    pub main_window_id: window::Id,
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

    // Settings Window State
    pub settings_window_id: Option<window::Id>,
    pub pending_settings: Option<Settings>,
    pub settings_active_tab: usize,

    // Job Queue Dialog State
    pub job_queue_window_id: Option<window::Id>,
    pub selected_job_indices: Vec<usize>,
    pub has_clipboard: bool,
    pub is_processing: bool,
    pub job_queue_status: String,

    // Add Job Dialog State
    pub add_job_window_id: Option<window::Id>,
    pub add_job_sources: Vec<String>,
    pub add_job_error: String,
    pub is_finding_jobs: bool,

    // Manual Selection Dialog State
    pub manual_selection_window_id: Option<window::Id>,
    pub manual_selection_job_idx: Option<usize>,
    pub source_groups: Vec<SourceGroupState>,
    pub final_tracks: Vec<FinalTrackState>,
    pub attachment_sources: HashMap<String, bool>,
    pub external_subtitles: Vec<PathBuf>,
    pub manual_selection_info: String,

    // Track Settings Dialog State
    pub track_settings_window_id: Option<window::Id>,
    pub track_settings_idx: Option<usize>,
    pub track_settings: TrackSettingsState,

    // Window ID Mapping
    pub window_map: HashMap<window::Id, WindowKind>,
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
    pub summary: String,
    pub badges: String,
    pub is_blocked: bool,
}

/// State for a final track in the layout.
#[derive(Debug, Clone)]
pub struct FinalTrackState {
    pub track_id: usize,
    pub source_key: String,
    pub track_type: String,
    pub summary: String,
    pub is_default: bool,
    pub is_forced: bool,
    pub sync_to_source: String,
    pub has_custom_name: bool,
    pub custom_name: String,
}

/// State for track settings dialog.
#[derive(Debug, Clone, Default)]
pub struct TrackSettingsState {
    pub track_type: String,
    pub codec_id: String,
    pub selected_language_idx: usize,
    pub custom_name: String,
    pub perform_ocr: bool,
    pub convert_to_ass: bool,
    pub rescale: bool,
    pub size_multiplier_pct: i32,
}

impl App {
    /// Create and run the application.
    pub fn run(
        config: Arc<Mutex<ConfigManager>>,
        job_queue: Arc<Mutex<JobQueue>>,
        config_path: PathBuf,
        logs_dir: PathBuf,
    ) -> iced::Result {
        let archive_logs = {
            let cfg = config.lock().unwrap();
            cfg.settings().logging.archive_logs
        };

        let version_info = format!(
            "Video Sync GUI started.\nCore version: {}\nConfig: {}\nLogs: {}\n",
            vsg_core::version(),
            config_path.display(),
            logs_dir.display()
        );

        iced::daemon(
            move || {
                // Open the main window and get its actual ID
                let (main_window_id, open_task) = window::open(window::Settings {
                    size: Size::new(900.0, 700.0),
                    ..Default::default()
                });

                let mut window_map = HashMap::new();
                window_map.insert(main_window_id, WindowKind::Main);

                let app = App {
                    config: config.clone(),
                    job_queue: job_queue.clone(),

                    main_window_id,
                    source1_path: String::new(),
                    source2_path: String::new(),
                    source3_path: String::new(),
                    archive_logs,
                    status_text: "Ready".to_string(),
                    progress_value: 0.0,
                    delay_source2: String::new(),
                    delay_source3: String::new(),
                    log_text: version_info.clone(),
                    is_analyzing: false,

                    settings_window_id: None,
                    pending_settings: None,
                    settings_active_tab: 0,

                    job_queue_window_id: None,
                    selected_job_indices: Vec::new(),
                    has_clipboard: false,
                    is_processing: false,
                    job_queue_status: String::new(),

                    add_job_window_id: None,
                    add_job_sources: vec![String::new(), String::new()],
                    add_job_error: String::new(),
                    is_finding_jobs: false,

                    manual_selection_window_id: None,
                    manual_selection_job_idx: None,
                    source_groups: Vec::new(),
                    final_tracks: Vec::new(),
                    attachment_sources: HashMap::new(),
                    external_subtitles: Vec::new(),
                    manual_selection_info: String::new(),

                    track_settings_window_id: None,
                    track_settings_idx: None,
                    track_settings: TrackSettingsState::default(),

                    window_map,
                };

                (app, open_task.map(|_| Message::Noop))
            },
            Self::update,
            Self::view,
        )
        .title(Self::title)
        .theme(Self::theme)
        .subscription(Self::subscription)
        .run()
    }

    fn title(&self, id: window::Id) -> String {
        if id == self.main_window_id {
            "Video Sync GUI".to_string()
        } else if self.settings_window_id == Some(id) {
            "Settings - Video Sync GUI".to_string()
        } else if self.job_queue_window_id == Some(id) {
            "Job Queue - Video Sync GUI".to_string()
        } else if self.add_job_window_id == Some(id) {
            "Add Jobs - Video Sync GUI".to_string()
        } else if self.manual_selection_window_id == Some(id) {
            "Manual Selection - Video Sync GUI".to_string()
        } else if self.track_settings_window_id == Some(id) {
            "Track Settings - Video Sync GUI".to_string()
        } else {
            "Video Sync GUI".to_string()
        }
    }

    fn theme(&self, _id: window::Id) -> Theme {
        Theme::Dark
    }

    fn subscription(&self) -> Subscription<Message> {
        window::close_events().map(Message::WindowClosed)
    }

    fn update(&mut self, message: Message) -> Task<Message> {
        match message {
            Message::OpenSettings => self.open_settings_window(),
            Message::CloseSettings => self.close_settings_window(),
            Message::CancelSettings => self.close_settings_window(),
            Message::OpenJobQueue => self.open_job_queue_window(),
            Message::CloseJobQueue => self.close_job_queue_window(),
            Message::OpenAddJob => self.open_add_job_window(),
            Message::CloseAddJob => self.close_add_job_window(),
            Message::OpenManualSelection(idx) => self.open_manual_selection_window(idx),
            Message::CloseManualSelection => self.close_manual_selection_window(),
            Message::OpenTrackSettings(idx) => self.open_track_settings_window(idx),
            Message::CloseTrackSettings => self.close_track_settings_window(),
            Message::WindowClosed(id) => self.handle_window_closed(id),
            Message::WindowOpened(window_kind, id) => self.handle_window_opened(window_kind, id),

            Message::SourcePathChanged(idx, path) => {
                self.handle_source_path_changed(idx, path);
                Task::none()
            }
            Message::BrowseSource(idx) => self.browse_source(idx),
            Message::FileSelected(idx, path) => {
                self.handle_file_selected(idx, path);
                Task::none()
            }
            Message::AnalyzeOnly => self.start_analysis(),
            Message::ArchiveLogsChanged(value) => {
                self.archive_logs = value;
                Task::none()
            }
            Message::AnalysisProgress(progress) => {
                self.progress_value = progress;
                Task::none()
            }
            Message::AnalysisLog(msg) => {
                self.append_log(&msg);
                Task::none()
            }
            Message::AnalysisComplete {
                delay_source2_ms,
                delay_source3_ms,
            } => {
                self.handle_analysis_complete(delay_source2_ms, delay_source3_ms);
                Task::none()
            }
            Message::AnalysisFailed(error) => {
                self.handle_analysis_failed(&error);
                Task::none()
            }

            Message::SettingChanged(key, value) => {
                self.handle_setting_changed(key, value);
                Task::none()
            }
            Message::SaveSettings => {
                self.save_settings();
                self.close_settings_window()
            }
            Message::BrowseFolder(folder_type) => self.browse_folder(folder_type),
            Message::FolderSelected(folder_type, path) => {
                self.handle_folder_selected(folder_type, path);
                Task::none()
            }
            Message::SettingsTabSelected(tab) => {
                self.settings_active_tab = tab;
                Task::none()
            }

            Message::AddJobsClicked => self.open_add_job_window(),
            Message::JobRowSelected(idx, selected) => {
                self.handle_job_row_selected(idx, selected);
                Task::none()
            }
            Message::JobRowDoubleClicked(idx) => self.open_manual_selection_window(idx),
            Message::RemoveSelectedJobs => {
                self.remove_selected_jobs();
                Task::none()
            }
            Message::MoveJobsUp => {
                self.move_jobs_up();
                Task::none()
            }
            Message::MoveJobsDown => {
                self.move_jobs_down();
                Task::none()
            }
            Message::CopyLayout(idx) => {
                self.copy_layout(idx);
                Task::none()
            }
            Message::PasteLayout => {
                self.paste_layout();
                Task::none()
            }
            Message::StartProcessing => self.start_processing(),
            Message::ProcessingProgress { .. } => Task::none(),
            Message::ProcessingComplete => {
                self.is_processing = false;
                self.job_queue_status = "Processing complete".to_string();
                Task::none()
            }
            Message::ProcessingFailed(error) => {
                self.is_processing = false;
                self.job_queue_status = format!("Processing failed: {}", error);
                Task::none()
            }

            Message::AddSource => {
                if self.add_job_sources.len() < 10 {
                    self.add_job_sources.push(String::new());
                }
                Task::none()
            }
            Message::RemoveSource(idx) => {
                if self.add_job_sources.len() > 2 && idx < self.add_job_sources.len() {
                    self.add_job_sources.remove(idx);
                }
                Task::none()
            }
            Message::AddJobSourceChanged(idx, path) => {
                if idx < self.add_job_sources.len() {
                    self.add_job_sources[idx] = path;
                }
                Task::none()
            }
            Message::AddJobBrowseSource(idx) => self.browse_add_job_source(idx),
            Message::AddJobFileSelected(idx, path) => {
                self.handle_add_job_file_selected(idx, path);
                Task::none()
            }
            Message::FindAndAddJobs => self.find_and_add_jobs(),
            Message::JobsAdded(count) => {
                self.is_finding_jobs = false;
                if count > 0 {
                    self.job_queue_status = format!("Added {} job(s)", count);
                    self.close_add_job_window()
                } else {
                    self.add_job_error = "No jobs could be discovered".to_string();
                    Task::none()
                }
            }

            Message::SourceTrackDoubleClicked { track_id, source_key } => {
                self.add_track_to_final_list(track_id, &source_key);
                Task::none()
            }
            Message::FinalTrackMoved(from, to) => {
                self.move_final_track(from, to);
                Task::none()
            }
            Message::FinalTrackRemoved(idx) => {
                self.remove_final_track(idx);
                Task::none()
            }
            Message::FinalTrackDefaultChanged(idx, value) => {
                if let Some(track) = self.final_tracks.get_mut(idx) {
                    track.is_default = value;
                }
                Task::none()
            }
            Message::FinalTrackForcedChanged(idx, value) => {
                if let Some(track) = self.final_tracks.get_mut(idx) {
                    track.is_forced = value;
                }
                Task::none()
            }
            Message::FinalTrackSyncChanged(idx, source) => {
                if let Some(track) = self.final_tracks.get_mut(idx) {
                    track.sync_to_source = source;
                }
                Task::none()
            }
            Message::FinalTrackSettingsClicked(idx) => self.open_track_settings_window(idx),
            Message::AttachmentToggled(source, checked) => {
                self.attachment_sources.insert(source, checked);
                Task::none()
            }
            Message::AddExternalSubtitles => self.browse_external_subtitles(),
            Message::ExternalFilesSelected(paths) => {
                self.external_subtitles.extend(paths);
                Task::none()
            }
            Message::AcceptLayout => {
                self.accept_layout();
                self.close_manual_selection_window()
            }

            Message::TrackLanguageChanged(idx) => {
                self.track_settings.selected_language_idx = idx;
                Task::none()
            }
            Message::TrackCustomNameChanged(name) => {
                self.track_settings.custom_name = name;
                Task::none()
            }
            Message::TrackPerformOcrChanged(value) => {
                self.track_settings.perform_ocr = value;
                Task::none()
            }
            Message::TrackConvertToAssChanged(value) => {
                self.track_settings.convert_to_ass = value;
                Task::none()
            }
            Message::TrackRescaleChanged(value) => {
                self.track_settings.rescale = value;
                Task::none()
            }
            Message::TrackSizeMultiplierChanged(value) => {
                self.track_settings.size_multiplier_pct = value;
                Task::none()
            }
            Message::ConfigureSyncExclusion => Task::none(),
            Message::AcceptTrackSettings => {
                self.accept_track_settings();
                self.close_track_settings_window()
            }

            Message::OpenStyleEditor(_) | Message::CloseStyleEditor => Task::none(),
            Message::OpenGeneratedTrack | Message::CloseGeneratedTrack => Task::none(),
            Message::OpenSyncExclusion | Message::CloseSyncExclusion => Task::none(),
            Message::OpenSourceSettings(_) | Message::CloseSourceSettings => Task::none(),

            Message::Noop => Task::none(),
        }
    }

    fn view(&self, id: window::Id) -> Element<Message> {
        match self.window_map.get(&id) {
            Some(WindowKind::Main) => pages::main_window::view(self),
            Some(WindowKind::Settings) => windows::settings::view(self),
            Some(WindowKind::JobQueue) => windows::job_queue::view(self),
            Some(WindowKind::AddJob) => windows::add_job::view(self),
            Some(WindowKind::ManualSelection(_)) => windows::manual_selection::view(self),
            Some(WindowKind::TrackSettings(_)) => windows::track_settings::view(self),
            _ => {
                // Fallback: If window is main window ID but not in map yet
                if id == self.main_window_id {
                    pages::main_window::view(self)
                } else {
                    widget::container(text("Loading..."))
                        .padding(20)
                        .into()
                }
            }
        }
    }

    pub fn append_log(&mut self, message: &str) {
        self.log_text.push_str(message);
        self.log_text.push('\n');
    }

    pub fn source_keys(&self) -> Vec<String> {
        self.source_groups.iter().map(|g| g.source_key.clone()).collect()
    }
}
