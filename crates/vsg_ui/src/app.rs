//! Main application module for Video Sync GUI.
//!
//! This module contains the core Application struct, Message enum,
//! and the update/view logic following the libcosmic MVU pattern.

use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::{Arc, Mutex};

use cosmic::app::{Command, Core, Settings as AppSettings};
use cosmic::iced::window;
use cosmic::iced_core::Size;
use cosmic::widget;
use cosmic::{Application, ApplicationExt, Element};

use vsg_core::config::{ConfigManager, Settings};
use vsg_core::jobs::JobQueue;
use vsg_core::logging::{GuiLogCallback, JobLogger, LogConfig};
use vsg_core::models::JobSpec;
use vsg_core::orchestrator::{AnalyzeStep, Context, JobState, Pipeline};

use crate::pages;
use crate::windows;

/// Application ID for COSMIC desktop integration.
pub const APP_ID: &str = "com.videosync.gui";

/// Unique identifier for windows.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum WindowId {
    Main,
    Settings,
    JobQueue,
    AddJob,
    ManualSelection(usize), // Job index
    TrackSettings(usize),   // Track index in current layout
}

/// All possible messages the application can receive.
#[derive(Debug, Clone)]
pub enum Message {
    // =========================================================================
    // Window Management
    // =========================================================================
    /// Open the settings window
    OpenSettings,
    /// Close the settings window
    CloseSettings,
    /// Open the job queue dialog
    OpenJobQueue,
    /// Close the job queue dialog
    CloseJobQueue,
    /// Open the add job dialog
    OpenAddJob,
    /// Close the add job dialog
    CloseAddJob,
    /// Open manual selection for a job
    OpenManualSelection(usize),
    /// Close manual selection
    CloseManualSelection,
    /// Open track settings for a track
    OpenTrackSettings(usize),
    /// Close track settings
    CloseTrackSettings,
    /// Window closed by user
    WindowClosed(window::Id),
    /// Window opened successfully
    WindowOpened(WindowId, window::Id),

    // =========================================================================
    // Main Window
    // =========================================================================
    /// Source path changed (index 1-3, path)
    SourcePathChanged(usize, String),
    /// Browse button clicked for source
    BrowseSource(usize),
    /// File selected from browse dialog
    FileSelected(usize, Option<PathBuf>),
    /// Analyze Only button clicked
    AnalyzeOnly,
    /// Archive logs checkbox changed
    ArchiveLogsChanged(bool),
    /// Analysis progress update
    AnalysisProgress(f32),
    /// Analysis log message
    AnalysisLog(String),
    /// Analysis completed
    AnalysisComplete {
        delay_source2_ms: Option<i64>,
        delay_source3_ms: Option<i64>,
    },
    /// Analysis failed
    AnalysisFailed(String),

    // =========================================================================
    // Settings Window
    // =========================================================================
    /// Setting value changed
    SettingChanged(SettingKey, SettingValue),
    /// Save settings
    SaveSettings,
    /// Browse for folder in settings
    BrowseFolder(FolderType),
    /// Folder selected from browse dialog
    FolderSelected(FolderType, Option<PathBuf>),

    // =========================================================================
    // Job Queue Dialog
    // =========================================================================
    /// Add jobs button clicked
    AddJobsClicked,
    /// Row selected/deselected (index, selected)
    JobRowSelected(usize, bool),
    /// Row double-clicked (open manual selection)
    JobRowDoubleClicked(usize),
    /// Remove selected jobs
    RemoveSelectedJobs,
    /// Move selected jobs up
    MoveJobsUp,
    /// Move selected jobs down
    MoveJobsDown,
    /// Copy layout from job
    CopyLayout(usize),
    /// Paste layout to selected jobs
    PasteLayout,
    /// Start processing queue
    StartProcessing,
    /// Processing progress update
    ProcessingProgress { job_idx: usize, progress: f32 },
    /// Processing completed
    ProcessingComplete,
    /// Processing failed
    ProcessingFailed(String),

    // =========================================================================
    // Add Job Dialog
    // =========================================================================
    /// Add another source input
    AddSource,
    /// Remove source input (index)
    RemoveSource(usize),
    /// Source path changed in add job dialog
    AddJobSourceChanged(usize, String),
    /// Browse source in add job dialog
    AddJobBrowseSource(usize),
    /// File selected for add job source
    AddJobFileSelected(usize, Option<PathBuf>),
    /// Find and add jobs
    FindAndAddJobs,
    /// Jobs discovered and added
    JobsAdded(usize),

    // =========================================================================
    // Manual Selection Dialog
    // =========================================================================
    /// Source track double-clicked (add to final list)
    SourceTrackDoubleClicked { track_id: usize, source_key: String },
    /// Final track moved (from, to)
    FinalTrackMoved(usize, usize),
    /// Final track removed
    FinalTrackRemoved(usize),
    /// Final track default flag changed
    FinalTrackDefaultChanged(usize, bool),
    /// Final track forced flag changed
    FinalTrackForcedChanged(usize, bool),
    /// Final track sync source changed
    FinalTrackSyncChanged(usize, String),
    /// Final track settings clicked
    FinalTrackSettingsClicked(usize),
    /// Attachment source toggled
    AttachmentToggled(String, bool),
    /// Add external subtitles clicked
    AddExternalSubtitles,
    /// External files selected
    ExternalFilesSelected(Vec<PathBuf>),
    /// Accept layout
    AcceptLayout,
    /// Cancel layout

    // =========================================================================
    // Track Settings Dialog
    // =========================================================================
    /// Language changed
    TrackLanguageChanged(usize),
    /// Custom name changed
    TrackCustomNameChanged(String),
    /// Perform OCR changed
    TrackPerformOcrChanged(bool),
    /// Convert to ASS changed
    TrackConvertToAssChanged(bool),
    /// Rescale changed
    TrackRescaleChanged(bool),
    /// Size multiplier changed
    TrackSizeMultiplierChanged(i32),
    /// Configure sync exclusion clicked
    ConfigureSyncExclusion,
    /// Accept track settings
    AcceptTrackSettings,
    /// Cancel track settings

    // =========================================================================
    // Stub Dialogs (placeholders)
    // =========================================================================
    /// Open style editor for track
    OpenStyleEditor(usize),
    /// Close style editor
    CloseStyleEditor,
    /// Open generated track dialog
    OpenGeneratedTrack,
    /// Close generated track dialog
    CloseGeneratedTrack,
    /// Open sync exclusion dialog
    OpenSyncExclusion,
    /// Close sync exclusion dialog
    CloseSyncExclusion,
    /// Open source settings dialog
    OpenSourceSettings(String),
    /// Close source settings dialog
    CloseSourceSettings,

    // =========================================================================
    // Internal
    // =========================================================================
    /// No operation (used for disabled buttons, etc.)
    Noop,
}

/// Settings keys for type-safe settings updates.
#[derive(Debug, Clone, PartialEq)]
pub enum SettingKey {
    // Paths
    OutputFolder,
    TempRoot,
    LogsFolder,
    // Logging
    CompactLogging,
    Autoscroll,
    ErrorTail,
    ProgressStep,
    ShowOptionsPretty,
    ShowOptionsJson,
    // Analysis
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
    // Delay Selection
    DelaySelectionMode,
    MinAcceptedChunks,
    FirstStableMinChunks,
    FirstStableSkipUnstable,
    EarlyClusterWindow,
    EarlyClusterThreshold,
    // Chapters
    ChapterRename,
    ChapterSnap,
    SnapMode,
    SnapThresholdMs,
    SnapStartsOnly,
    // Post-process
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
    /// Core application state (from libcosmic)
    core: Core,

    /// Configuration manager
    pub config: Arc<Mutex<ConfigManager>>,

    /// Job queue
    pub job_queue: Arc<Mutex<JobQueue>>,

    // =========================================================================
    // Main Window State
    // =========================================================================
    /// Source 1 path (reference)
    pub source1_path: String,
    /// Source 2 path
    pub source2_path: String,
    /// Source 3 path
    pub source3_path: String,
    /// Archive logs after batch
    pub archive_logs: bool,
    /// Current status text
    pub status_text: String,
    /// Progress value (0-100)
    pub progress_value: f32,
    /// Delay result for source 2
    pub delay_source2: String,
    /// Delay result for source 3
    pub delay_source3: String,
    /// Log text
    pub log_text: String,
    /// Is analysis running
    pub is_analyzing: bool,

    // =========================================================================
    // Settings Window State
    // =========================================================================
    /// Settings window ID (if open)
    pub settings_window_id: Option<window::Id>,
    /// Pending settings (edited but not saved)
    pub pending_settings: Option<Settings>,

    // =========================================================================
    // Job Queue Dialog State
    // =========================================================================
    /// Job queue window ID (if open)
    pub job_queue_window_id: Option<window::Id>,
    /// Selected job indices
    pub selected_job_indices: Vec<usize>,
    /// Has layout in clipboard
    pub has_clipboard: bool,
    /// Is processing queue
    pub is_processing: bool,
    /// Status message for job queue
    pub job_queue_status: String,

    // =========================================================================
    // Add Job Dialog State
    // =========================================================================
    /// Add job window ID (if open)
    pub add_job_window_id: Option<window::Id>,
    /// Source paths in add job dialog
    pub add_job_sources: Vec<String>,
    /// Error message in add job dialog
    pub add_job_error: String,
    /// Is finding jobs
    pub is_finding_jobs: bool,

    // =========================================================================
    // Manual Selection Dialog State
    // =========================================================================
    /// Manual selection window ID (if open)
    pub manual_selection_window_id: Option<window::Id>,
    /// Current job index being configured
    pub manual_selection_job_idx: Option<usize>,
    /// Source groups with tracks
    pub source_groups: Vec<SourceGroupState>,
    /// Final tracks in layout
    pub final_tracks: Vec<FinalTrackState>,
    /// Attachment source selections
    pub attachment_sources: HashMap<String, bool>,
    /// External subtitle paths
    pub external_subtitles: Vec<PathBuf>,
    /// Info message for manual selection
    pub manual_selection_info: String,

    // =========================================================================
    // Track Settings Dialog State
    // =========================================================================
    /// Track settings window ID (if open)
    pub track_settings_window_id: Option<window::Id>,
    /// Current track index being configured
    pub track_settings_idx: Option<usize>,
    /// Track settings state
    pub track_settings: TrackSettingsState,

    // =========================================================================
    // Window ID Mapping
    // =========================================================================
    /// Map window IDs to our WindowId enum
    pub window_map: HashMap<window::Id, WindowId>,
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

impl Application for App {
    type Executor = cosmic::executor::Default;
    type Flags = AppFlags;
    type Message = Message;

    const APP_ID: &'static str = APP_ID;

    fn core(&self) -> &Core {
        &self.core
    }

    fn core_mut(&mut self) -> &mut Core {
        &mut self.core
    }

    fn init(core: Core, flags: Self::Flags) -> (Self, Command<Self::Message>) {
        let archive_logs = {
            let cfg = flags.config.lock().unwrap();
            cfg.settings().logging.archive_logs
        };

        let version_info = format!(
            "Video Sync GUI started.\nCore version: {}\nConfig: {}\nLogs: {}\n",
            vsg_core::version(),
            flags.config_path.display(),
            flags.logs_dir.display()
        );

        let app = Self {
            core,
            config: flags.config,
            job_queue: flags.job_queue,

            // Main window state
            source1_path: String::new(),
            source2_path: String::new(),
            source3_path: String::new(),
            archive_logs,
            status_text: "Ready".to_string(),
            progress_value: 0.0,
            delay_source2: String::new(),
            delay_source3: String::new(),
            log_text: version_info,
            is_analyzing: false,

            // Settings window state
            settings_window_id: None,
            pending_settings: None,

            // Job queue state
            job_queue_window_id: None,
            selected_job_indices: Vec::new(),
            has_clipboard: false,
            is_processing: false,
            job_queue_status: String::new(),

            // Add job state
            add_job_window_id: None,
            add_job_sources: vec![String::new(), String::new()],
            add_job_error: String::new(),
            is_finding_jobs: false,

            // Manual selection state
            manual_selection_window_id: None,
            manual_selection_job_idx: None,
            source_groups: Vec::new(),
            final_tracks: Vec::new(),
            attachment_sources: HashMap::new(),
            external_subtitles: Vec::new(),
            manual_selection_info: String::new(),

            // Track settings state
            track_settings_window_id: None,
            track_settings_idx: None,
            track_settings: TrackSettingsState::default(),

            // Window mapping
            window_map: HashMap::new(),
        };

        (app, Command::none())
    }

    fn update(&mut self, message: Self::Message) -> Command<Self::Message> {
        match message {
            // Window management
            Message::OpenSettings => self.open_settings_window(),
            Message::CloseSettings => self.close_settings_window(),
            Message::OpenJobQueue => self.open_job_queue_window(),
            Message::CloseJobQueue => self.close_job_queue_window(),
            Message::OpenAddJob => self.open_add_job_window(),
            Message::CloseAddJob => self.close_add_job_window(),
            Message::OpenManualSelection(idx) => self.open_manual_selection_window(idx),
            Message::CloseManualSelection => self.close_manual_selection_window(),
            Message::OpenTrackSettings(idx) => self.open_track_settings_window(idx),
            Message::CloseTrackSettings => self.close_track_settings_window(),
            Message::WindowClosed(id) => self.handle_window_closed(id),
            Message::WindowOpened(window_id, id) => self.handle_window_opened(window_id, id),

            // Main window
            Message::SourcePathChanged(idx, path) => {
                self.handle_source_path_changed(idx, path);
                Command::none()
            }
            Message::BrowseSource(idx) => self.browse_source(idx),
            Message::FileSelected(idx, path) => {
                self.handle_file_selected(idx, path);
                Command::none()
            }
            Message::AnalyzeOnly => self.start_analysis(),
            Message::ArchiveLogsChanged(value) => {
                self.archive_logs = value;
                Command::none()
            }
            Message::AnalysisProgress(progress) => {
                self.progress_value = progress;
                Command::none()
            }
            Message::AnalysisLog(msg) => {
                self.append_log(&msg);
                Command::none()
            }
            Message::AnalysisComplete {
                delay_source2_ms,
                delay_source3_ms,
            } => {
                self.handle_analysis_complete(delay_source2_ms, delay_source3_ms);
                Command::none()
            }
            Message::AnalysisFailed(error) => {
                self.handle_analysis_failed(&error);
                Command::none()
            }

            // Settings
            Message::SettingChanged(key, value) => {
                self.handle_setting_changed(key, value);
                Command::none()
            }
            Message::SaveSettings => {
                self.save_settings();
                self.close_settings_window()
            }
            Message::BrowseFolder(folder_type) => self.browse_folder(folder_type),
            Message::FolderSelected(folder_type, path) => {
                self.handle_folder_selected(folder_type, path);
                Command::none()
            }

            // Job queue
            Message::AddJobsClicked => self.open_add_job_window(),
            Message::JobRowSelected(idx, selected) => {
                self.handle_job_row_selected(idx, selected);
                Command::none()
            }
            Message::JobRowDoubleClicked(idx) => self.open_manual_selection_window(idx),
            Message::RemoveSelectedJobs => {
                self.remove_selected_jobs();
                Command::none()
            }
            Message::MoveJobsUp => {
                self.move_jobs_up();
                Command::none()
            }
            Message::MoveJobsDown => {
                self.move_jobs_down();
                Command::none()
            }
            Message::CopyLayout(idx) => {
                self.copy_layout(idx);
                Command::none()
            }
            Message::PasteLayout => {
                self.paste_layout();
                Command::none()
            }
            Message::StartProcessing => self.start_processing(),
            Message::ProcessingProgress { job_idx, progress } => {
                // Update progress display
                Command::none()
            }
            Message::ProcessingComplete => {
                self.is_processing = false;
                self.job_queue_status = "Processing complete".to_string();
                Command::none()
            }
            Message::ProcessingFailed(error) => {
                self.is_processing = false;
                self.job_queue_status = format!("Processing failed: {}", error);
                Command::none()
            }

            // Add job
            Message::AddSource => {
                if self.add_job_sources.len() < 10 {
                    self.add_job_sources.push(String::new());
                }
                Command::none()
            }
            Message::RemoveSource(idx) => {
                if self.add_job_sources.len() > 2 && idx < self.add_job_sources.len() {
                    self.add_job_sources.remove(idx);
                }
                Command::none()
            }
            Message::AddJobSourceChanged(idx, path) => {
                if idx < self.add_job_sources.len() {
                    self.add_job_sources[idx] = path;
                }
                Command::none()
            }
            Message::AddJobBrowseSource(idx) => self.browse_add_job_source(idx),
            Message::AddJobFileSelected(idx, path) => {
                self.handle_add_job_file_selected(idx, path);
                Command::none()
            }
            Message::FindAndAddJobs => self.find_and_add_jobs(),
            Message::JobsAdded(count) => {
                self.is_finding_jobs = false;
                if count > 0 {
                    self.job_queue_status = format!("Added {} job(s)", count);
                    self.close_add_job_window()
                } else {
                    self.add_job_error = "No jobs could be discovered".to_string();
                    Command::none()
                }
            }

            // Manual selection
            Message::SourceTrackDoubleClicked { track_id, source_key } => {
                self.add_track_to_final_list(track_id, &source_key);
                Command::none()
            }
            Message::FinalTrackMoved(from, to) => {
                self.move_final_track(from, to);
                Command::none()
            }
            Message::FinalTrackRemoved(idx) => {
                self.remove_final_track(idx);
                Command::none()
            }
            Message::FinalTrackDefaultChanged(idx, value) => {
                if let Some(track) = self.final_tracks.get_mut(idx) {
                    track.is_default = value;
                }
                Command::none()
            }
            Message::FinalTrackForcedChanged(idx, value) => {
                if let Some(track) = self.final_tracks.get_mut(idx) {
                    track.is_forced = value;
                }
                Command::none()
            }
            Message::FinalTrackSyncChanged(idx, source) => {
                if let Some(track) = self.final_tracks.get_mut(idx) {
                    track.sync_to_source = source;
                }
                Command::none()
            }
            Message::FinalTrackSettingsClicked(idx) => self.open_track_settings_window(idx),
            Message::AttachmentToggled(source, checked) => {
                self.attachment_sources.insert(source, checked);
                Command::none()
            }
            Message::AddExternalSubtitles => self.browse_external_subtitles(),
            Message::ExternalFilesSelected(paths) => {
                self.external_subtitles.extend(paths);
                Command::none()
            }
            Message::AcceptLayout => {
                self.accept_layout();
                self.close_manual_selection_window()
            }

            // Track settings
            Message::TrackLanguageChanged(idx) => {
                self.track_settings.selected_language_idx = idx;
                Command::none()
            }
            Message::TrackCustomNameChanged(name) => {
                self.track_settings.custom_name = name;
                Command::none()
            }
            Message::TrackPerformOcrChanged(value) => {
                self.track_settings.perform_ocr = value;
                Command::none()
            }
            Message::TrackConvertToAssChanged(value) => {
                self.track_settings.convert_to_ass = value;
                Command::none()
            }
            Message::TrackRescaleChanged(value) => {
                self.track_settings.rescale = value;
                Command::none()
            }
            Message::TrackSizeMultiplierChanged(value) => {
                self.track_settings.size_multiplier_pct = value;
                Command::none()
            }
            Message::ConfigureSyncExclusion => {
                // TODO: Open sync exclusion dialog
                Command::none()
            }
            Message::AcceptTrackSettings => {
                self.accept_track_settings();
                self.close_track_settings_window()
            }

            // Stub dialogs
            Message::OpenStyleEditor(_) | Message::CloseStyleEditor => Command::none(),
            Message::OpenGeneratedTrack | Message::CloseGeneratedTrack => Command::none(),
            Message::OpenSyncExclusion | Message::CloseSyncExclusion => Command::none(),
            Message::OpenSourceSettings(_) | Message::CloseSourceSettings => Command::none(),

            Message::Noop => Command::none(),
        }
    }

    fn view(&self) -> Element<Self::Message> {
        pages::main_window::view(self)
    }

    fn view_window(&self, id: window::Id) -> Element<Self::Message> {
        match self.window_map.get(&id) {
            Some(WindowId::Settings) => windows::settings::view(self),
            Some(WindowId::JobQueue) => windows::job_queue::view(self),
            Some(WindowId::AddJob) => windows::add_job::view(self),
            Some(WindowId::ManualSelection(_)) => windows::manual_selection::view(self),
            Some(WindowId::TrackSettings(_)) => windows::track_settings::view(self),
            _ => widget::text("Unknown window").into(),
        }
    }
}

/// Application flags for initialization.
pub struct AppFlags {
    pub config: Arc<Mutex<ConfigManager>>,
    pub job_queue: Arc<Mutex<JobQueue>>,
    pub config_path: PathBuf,
    pub logs_dir: PathBuf,
}

impl App {
    /// Append text to the log panel.
    pub fn append_log(&mut self, message: &str) {
        self.log_text.push_str(message);
        self.log_text.push('\n');
    }

    /// Get sorted source keys.
    pub fn source_keys(&self) -> Vec<String> {
        self.source_groups.iter().map(|g| g.source_key.clone()).collect()
    }
}
