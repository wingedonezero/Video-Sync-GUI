//! Handler methods for the App struct.
//!
//! This module contains all the business logic handlers separated from the
//! main app module for better organization.

use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Command as StdCommand;

use cosmic::app::Task;
use cosmic::iced::window;
use cosmic::iced_core::Size;
use cosmic::Action;

use vsg_core::config::Settings;
use vsg_core::jobs::{discover_jobs, FinalTrackEntry, ManualLayout};
use vsg_core::logging::{JobLogger, LogConfig};
use vsg_core::models::{
    AnalysisMode, CorrelationMethod, DelaySelectionMode, FilteringMethod, JobSpec, SnapMode,
    SyncMode, TrackType,
};
use vsg_core::orchestrator::{AnalyzeStep, Context, JobState, Pipeline};

use crate::app::{
    App, FinalTrackState, FolderType, Message, SettingKey, SettingValue, SourceGroupState,
    TrackWidgetState, WindowId,
};

impl App {
    // =========================================================================
    // Window Management
    // =========================================================================

    /// Open the settings window.
    pub fn open_settings_window(&mut self) -> Task<Message> {
        if self.settings_window_id.is_some() {
            return Task::none();
        }

        // Clone current settings for editing
        let cfg = self.config.lock().unwrap();
        self.pending_settings = Some(cfg.settings().clone());
        drop(cfg);

        let settings = window::Settings {
            size: Size::new(800.0, 700.0),
            resizable: true,
            ..Default::default()
        };

        let (id, command) = window::open(settings);
        self.window_map.insert(id, WindowId::Settings);
        self.settings_window_id = Some(id);

        command.map(|_| Action::App(Message::Noop))
    }

    /// Close the settings window.
    pub fn close_settings_window(&mut self) -> Task<Message> {
        if let Some(id) = self.settings_window_id.take() {
            self.window_map.remove(&id);
            self.pending_settings = None;
            return window::close::<Action<Message>>(id);
        }
        Task::none()
    }

    /// Open the job queue window.
    pub fn open_job_queue_window(&mut self) -> Task<Message> {
        if self.job_queue_window_id.is_some() {
            return Task::none();
        }

        self.append_log("Opening job queue...");

        let settings = window::Settings {
            size: Size::new(1100.0, 600.0),
            resizable: true,
            ..Default::default()
        };

        let (id, command) = window::open(settings);
        self.window_map.insert(id, WindowId::JobQueue);
        self.job_queue_window_id = Some(id);

        command.map(|_| Action::App(Message::Noop))
    }

    /// Close the job queue window.
    pub fn close_job_queue_window(&mut self) -> Task<Message> {
        if let Some(id) = self.job_queue_window_id.take() {
            self.window_map.remove(&id);
            return window::close::<Action<Message>>(id);
        }
        Task::none()
    }

    /// Open the add job window.
    pub fn open_add_job_window(&mut self) -> Task<Message> {
        if self.add_job_window_id.is_some() {
            return Task::none();
        }

        // Reset state
        self.add_job_sources = vec![String::new(), String::new()];
        self.add_job_error = String::new();
        self.is_finding_jobs = false;

        let settings = window::Settings {
            size: Size::new(700.0, 400.0),
            resizable: true,
            ..Default::default()
        };

        let (id, command) = window::open(settings);
        self.window_map.insert(id, WindowId::AddJob);
        self.add_job_window_id = Some(id);

        command.map(|_| Action::App(Message::Noop))
    }

    /// Close the add job window.
    pub fn close_add_job_window(&mut self) -> Task<Message> {
        if let Some(id) = self.add_job_window_id.take() {
            self.window_map.remove(&id);
            return window::close::<Action<Message>>(id);
        }
        Task::none()
    }

    /// Open the manual selection window for a job.
    pub fn open_manual_selection_window(&mut self, job_idx: usize) -> Task<Message> {
        if self.manual_selection_window_id.is_some() {
            return Task::none();
        }

        // Get job info
        let (sources, job_name) = {
            let q = self.job_queue.lock().unwrap();
            match q.get(job_idx) {
                Some(job) => (job.sources.clone(), job.name.clone()),
                None => {
                    self.job_queue_status = "Job not found".to_string();
                    return Task::none();
                }
            }
        };

        // Populate source groups
        self.populate_source_groups(&sources);
        self.manual_selection_job_idx = Some(job_idx);
        self.final_tracks.clear();
        self.attachment_sources.clear();

        // Default to Source 1 for attachments
        self.attachment_sources.insert("Source 1".to_string(), true);

        let settings = window::Settings {
            size: Size::new(1200.0, 800.0),
            resizable: true,
            ..Default::default()
        };

        let (id, command) = window::open(settings);
        self.window_map.insert(id, WindowId::ManualSelection(job_idx));
        self.manual_selection_window_id = Some(id);

        command.map(|_| Action::App(Message::Noop))
    }

    /// Close the manual selection window.
    pub fn close_manual_selection_window(&mut self) -> Task<Message> {
        if let Some(id) = self.manual_selection_window_id.take() {
            self.window_map.remove(&id);
            self.manual_selection_job_idx = None;
            self.source_groups.clear();
            self.final_tracks.clear();
            return window::close::<Action<Message>>(id);
        }
        Task::none()
    }

    /// Open the track settings window.
    pub fn open_track_settings_window(&mut self, track_idx: usize) -> Task<Message> {
        if self.track_settings_window_id.is_some() {
            return Task::none();
        }

        // Get track info
        if let Some(track) = self.final_tracks.get(track_idx) {
            self.track_settings.track_type = track.track_type.clone();
            self.track_settings.custom_name = track.custom_name.clone();
            self.track_settings_idx = Some(track_idx);
        }

        let settings = window::Settings {
            size: Size::new(500.0, 450.0),
            resizable: false,
            ..Default::default()
        };

        let (id, command) = window::open(settings);
        self.window_map.insert(id, WindowId::TrackSettings(track_idx));
        self.track_settings_window_id = Some(id);

        command.map(|_| Action::App(Message::Noop))
    }

    /// Close the track settings window.
    pub fn close_track_settings_window(&mut self) -> Task<Message> {
        if let Some(id) = self.track_settings_window_id.take() {
            self.window_map.remove(&id);
            self.track_settings_idx = None;
            return window::close::<Action<Message>>(id);
        }
        Task::none()
    }

    /// Handle window closed event.
    pub fn handle_window_closed(&mut self, id: window::Id) -> Task<Message> {
        if let Some(window_id) = self.window_map.remove(&id) {
            match window_id {
                WindowId::Settings => {
                    self.settings_window_id = None;
                    self.pending_settings = None;
                }
                WindowId::JobQueue => {
                    self.job_queue_window_id = None;
                }
                WindowId::AddJob => {
                    self.add_job_window_id = None;
                }
                WindowId::ManualSelection(_) => {
                    self.manual_selection_window_id = None;
                    self.manual_selection_job_idx = None;
                }
                WindowId::TrackSettings(_) => {
                    self.track_settings_window_id = None;
                    self.track_settings_idx = None;
                }
                _ => {}
            }
        }
        Task::none()
    }

    /// Handle window opened event.
    pub fn handle_window_opened(&mut self, window_id: WindowId, id: window::Id) -> Task<Message> {
        self.window_map.insert(id, window_id);
        Task::none()
    }

    // =========================================================================
    // File Browsing
    // =========================================================================

    /// Browse for a source file.
    pub fn browse_source(&self, idx: usize) -> Task<Message> {
        let title = match idx {
            1 => "Select Source 1 (Reference)",
            2 => "Select Source 2",
            3 => "Select Source 3",
            _ => "Select Source",
        };

        Task::perform(
            async move {
                let path = rfd::AsyncFileDialog::new()
                    .set_title(title)
                    .add_filter(
                        "Video Files",
                        &["mkv", "mp4", "avi", "mov", "webm", "m4v", "ts", "m2ts"],
                    )
                    .add_filter("All Files", &["*"])
                    .pick_file()
                    .await
                    .map(|f| f.path().to_path_buf());
                (idx, path)
            },
            |(idx, path)| Action::App(Message::FileSelected(idx, path)),
        )
    }

    /// Handle source path changed.
    pub fn handle_source_path_changed(&mut self, idx: usize, path: String) {
        let clean_path = clean_file_url(&path);
        match idx {
            1 => self.source1_path = clean_path.clone(),
            2 => self.source2_path = clean_path.clone(),
            3 => self.source3_path = clean_path.clone(),
            _ => {}
        }
        if !clean_path.is_empty() {
            self.append_log(&format!("Source {}: {}", idx, clean_path));
        }
    }

    /// Handle file selected from browser.
    pub fn handle_file_selected(&mut self, idx: usize, path: Option<PathBuf>) {
        if let Some(p) = path {
            let path_str = p.to_string_lossy().to_string();
            match idx {
                1 => self.source1_path = path_str.clone(),
                2 => self.source2_path = path_str.clone(),
                3 => self.source3_path = path_str.clone(),
                _ => {}
            }
            self.append_log(&format!("Source {}: {}", idx, path_str));
        }
    }

    /// Browse for a folder in settings.
    pub fn browse_folder(&self, folder_type: FolderType) -> Task<Message> {
        let title = match folder_type {
            FolderType::Output => "Select Output Directory",
            FolderType::Temp => "Select Temporary Directory",
            FolderType::Logs => "Select Logs Directory",
        };

        Task::perform(
            async move {
                let path = rfd::AsyncFileDialog::new()
                    .set_title(title)
                    .pick_folder()
                    .await
                    .map(|f| f.path().to_path_buf());
                (folder_type, path)
            },
            |(folder_type, path)| Action::App(Message::FolderSelected(folder_type, path)),
        )
    }

    /// Handle folder selected from browser.
    pub fn handle_folder_selected(&mut self, folder_type: FolderType, path: Option<PathBuf>) {
        if let (Some(settings), Some(p)) = (&mut self.pending_settings, path) {
            let path_str = p.to_string_lossy().to_string();
            match folder_type {
                FolderType::Output => settings.paths.output_folder = path_str,
                FolderType::Temp => settings.paths.temp_root = path_str,
                FolderType::Logs => settings.paths.logs_folder = path_str,
            }
        }
    }

    /// Browse for add job source file.
    pub fn browse_add_job_source(&self, idx: usize) -> Task<Message> {
        let title = if idx == 0 {
            "Select Source 1 (Reference)"
        } else {
            "Select Source"
        };

        Task::perform(
            async move {
                let path = rfd::AsyncFileDialog::new()
                    .set_title(title)
                    .add_filter(
                        "Video Files",
                        &["mkv", "mp4", "avi", "mov", "webm", "m4v", "ts", "m2ts"],
                    )
                    .add_filter("All Files", &["*"])
                    .pick_file()
                    .await
                    .map(|f| f.path().to_path_buf());
                (idx, path)
            },
            |(idx, path)| Action::App(Message::AddJobFileSelected(idx, path)),
        )
    }

    /// Handle add job file selected.
    pub fn handle_add_job_file_selected(&mut self, idx: usize, path: Option<PathBuf>) {
        if let Some(p) = path {
            if idx < self.add_job_sources.len() {
                self.add_job_sources[idx] = p.to_string_lossy().to_string();
            }
        }
    }

    /// Browse for external subtitles.
    pub fn browse_external_subtitles(&self) -> Task<Message> {
        Task::perform(
            async {
                let files = rfd::AsyncFileDialog::new()
                    .set_title("Select External Subtitle File(s)")
                    .add_filter("Subtitle Files", &["srt", "ass", "ssa", "sub", "idx", "sup"])
                    .add_filter("All Files", &["*"])
                    .pick_files()
                    .await
                    .map(|files| files.into_iter().map(|f| f.path().to_path_buf()).collect())
                    .unwrap_or_default();
                files
            },
            |files| Action::App(Message::ExternalFilesSelected(files)),
        )
    }

    // =========================================================================
    // Analysis
    // =========================================================================

    /// Start the analysis pipeline.
    pub fn start_analysis(&mut self) -> Task<Message> {
        if self.source1_path.is_empty() || self.source2_path.is_empty() {
            self.append_log("[WARNING] Please select at least Source 1 and Source 2");
            return Task::none();
        }

        self.is_analyzing = true;
        self.status_text = "Analyzing...".to_string();
        self.progress_value = 0.0;

        self.append_log("=== Starting Analysis ===");
        self.append_log(&format!("Source 1: {}", self.source1_path));
        self.append_log(&format!("Source 2: {}", self.source2_path));
        if !self.source3_path.is_empty() {
            self.append_log(&format!("Source 3: {}", self.source3_path));
        }

        // Build job spec
        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), PathBuf::from(&self.source1_path));
        sources.insert("Source 2".to_string(), PathBuf::from(&self.source2_path));
        if !self.source3_path.is_empty() {
            sources.insert("Source 3".to_string(), PathBuf::from(&self.source3_path));
        }

        let job_spec = JobSpec::new(sources);
        let settings = {
            let cfg = self.config.lock().unwrap();
            cfg.settings().clone()
        };

        // Run analysis in background
        Task::perform(
            async move { run_analyze_only(job_spec, settings).await },
            |result| Action::App(match result {
                Ok((delay2, delay3)) => Message::AnalysisComplete {
                    delay_source2_ms: delay2,
                    delay_source3_ms: delay3,
                },
                Err(e) => Message::AnalysisFailed(e),
            }),
        )
    }

    /// Handle analysis complete.
    pub fn handle_analysis_complete(
        &mut self,
        delay_source2_ms: Option<i64>,
        delay_source3_ms: Option<i64>,
    ) {
        self.is_analyzing = false;
        self.progress_value = 100.0;
        self.status_text = "Ready".to_string();

        if let Some(delay) = delay_source2_ms {
            self.delay_source2 = format!("{} ms", delay);
            self.append_log(&format!("Source 2 delay: {} ms", delay));
        }
        if let Some(delay) = delay_source3_ms {
            self.delay_source3 = format!("{} ms", delay);
            self.append_log(&format!("Source 3 delay: {} ms", delay));
        }

        self.append_log("=== Analysis Complete ===");
    }

    /// Handle analysis failed.
    pub fn handle_analysis_failed(&mut self, error: &str) {
        self.is_analyzing = false;
        self.progress_value = 0.0;
        self.status_text = "Analysis Failed".to_string();
        self.append_log(&format!("[ERROR] {}", error));
    }

    // =========================================================================
    // Settings
    // =========================================================================

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

    // =========================================================================
    // Job Queue
    // =========================================================================

    /// Handle job row selected.
    pub fn handle_job_row_selected(&mut self, idx: usize, selected: bool) {
        if selected {
            if !self.selected_job_indices.contains(&idx) {
                self.selected_job_indices.push(idx);
            }
        } else {
            self.selected_job_indices.retain(|&i| i != idx);
        }
    }

    /// Remove selected jobs.
    pub fn remove_selected_jobs(&mut self) {
        if self.selected_job_indices.is_empty() {
            return;
        }

        let count = self.selected_job_indices.len();
        {
            let mut q = self.job_queue.lock().unwrap();
            q.remove_indices(self.selected_job_indices.clone());
            if let Err(e) = q.save() {
                tracing::warn!("Failed to save queue: {}", e);
            }
        }

        self.selected_job_indices.clear();
        self.job_queue_status = format!("Removed {} job(s)", count);
    }

    /// Move selected jobs up.
    pub fn move_jobs_up(&mut self) {
        if self.selected_job_indices.is_empty() {
            return;
        }

        let mut q = self.job_queue.lock().unwrap();
        q.move_up(&self.selected_job_indices);
        if let Err(e) = q.save() {
            tracing::warn!("Failed to save queue: {}", e);
        }
    }

    /// Move selected jobs down.
    pub fn move_jobs_down(&mut self) {
        if self.selected_job_indices.is_empty() {
            return;
        }

        let mut q = self.job_queue.lock().unwrap();
        q.move_down(&self.selected_job_indices);
        if let Err(e) = q.save() {
            tracing::warn!("Failed to save queue: {}", e);
        }
    }

    /// Copy layout from a job.
    pub fn copy_layout(&mut self, idx: usize) {
        let mut q = self.job_queue.lock().unwrap();
        if q.copy_layout(idx) {
            self.has_clipboard = true;
            self.job_queue_status = "Layout copied to clipboard".to_string();
        } else {
            self.job_queue_status = "No layout to copy (job not configured)".to_string();
        }
    }

    /// Paste layout to selected jobs.
    pub fn paste_layout(&mut self) {
        if self.selected_job_indices.is_empty() {
            self.job_queue_status = "No jobs selected for paste".to_string();
            return;
        }

        let mut q = self.job_queue.lock().unwrap();
        let count = q.paste_layout(&self.selected_job_indices);
        if count > 0 {
            if let Err(e) = q.save() {
                tracing::warn!("Failed to save queue: {}", e);
            }
            self.job_queue_status = format!("Pasted layout to {} job(s)", count);
        } else {
            self.job_queue_status = "No layout in clipboard".to_string();
        }
    }

    /// Start processing the queue.
    pub fn start_processing(&mut self) -> Task<Message> {
        let q = self.job_queue.lock().unwrap();
        let ready_count = q.jobs_ready().len();

        if ready_count == 0 {
            self.job_queue_status =
                "No configured jobs to process. Double-click jobs to configure them.".to_string();
            return Task::none();
        }

        self.is_processing = true;
        self.job_queue_status = format!("Processing {} job(s)...", ready_count);

        // TODO: Implement actual queue processing
        Task::none()
    }

    /// Find and add jobs from source paths.
    pub fn find_and_add_jobs(&mut self) -> Task<Message> {
        // Validate Source 1 and 2
        if self.add_job_sources.is_empty() || self.add_job_sources[0].is_empty() {
            self.add_job_error = "Source 1 (Reference) is required.".to_string();
            return Task::none();
        }

        if self.add_job_sources.len() < 2 || self.add_job_sources[1].is_empty() {
            self.add_job_error = "Source 2 is required.".to_string();
            return Task::none();
        }

        self.is_finding_jobs = true;
        self.add_job_error.clear();

        // Collect source paths
        let sources: HashMap<String, PathBuf> = self
            .add_job_sources
            .iter()
            .enumerate()
            .filter(|(_, path)| !path.is_empty())
            .map(|(idx, path)| (format!("Source {}", idx + 1), PathBuf::from(path)))
            .collect();

        let job_queue = self.job_queue.clone();

        Task::perform(
            async move {
                match discover_jobs(&sources) {
                    Ok(jobs) if jobs.is_empty() => 0,
                    Ok(jobs) => {
                        let count = jobs.len();
                        {
                            let mut q = job_queue.lock().unwrap();
                            q.add_all(jobs);
                            if let Err(e) = q.save() {
                                tracing::warn!("Failed to save queue: {}", e);
                            }
                        }
                        count
                    }
                    Err(_) => 0,
                }
            },
            |count| Action::App(Message::JobsAdded(count)),
        )
    }

    // =========================================================================
    // Manual Selection
    // =========================================================================

    /// Populate source groups from sources.
    pub fn populate_source_groups(&mut self, sources: &HashMap<String, PathBuf>) {
        self.source_groups.clear();

        let mut source_keys: Vec<&String> = sources.keys().collect();
        source_keys.sort();

        for source_key in source_keys {
            let path = &sources[source_key];
            let is_reference = source_key == "Source 1";

            let tracks = probe_tracks(path);

            let file_name = path
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_else(|| path.to_string_lossy().to_string());

            let title = if is_reference {
                format!("{} (Reference) - '{}'", source_key, file_name)
            } else {
                format!("{} - '{}'", source_key, file_name)
            };

            self.source_groups.push(SourceGroupState {
                source_key: source_key.clone(),
                title,
                tracks: tracks
                    .into_iter()
                    .map(|t| {
                        let is_blocked = !is_reference && t.track_type == "video";
                        TrackWidgetState {
                            id: t.track_id,
                            track_type: t.track_type,
                            codec_id: t.codec_id,
                            summary: t.summary,
                            badges: t.badges,
                            is_blocked,
                        }
                    })
                    .collect(),
                is_expanded: true,
            });
        }
    }

    /// Add a track to the final list.
    pub fn add_track_to_final_list(&mut self, track_id: usize, source_key: &str) {
        // Find the track
        let track = self.source_groups.iter().find_map(|g| {
            if g.source_key == source_key {
                g.tracks.iter().find(|t| t.id == track_id).cloned()
            } else {
                None
            }
        });

        if let Some(track) = track {
            if track.is_blocked {
                self.manual_selection_info =
                    "Video tracks can only be added from the reference source.".to_string();
                return;
            }

            self.final_tracks.push(FinalTrackState {
                track_id,
                source_key: source_key.to_string(),
                track_type: track.track_type,
                summary: track.summary,
                is_default: false,
                is_forced: false,
                sync_to_source: "Source 1".to_string(),
                has_custom_name: false,
                custom_name: String::new(),
            });

            self.manual_selection_info.clear();
        }
    }

    /// Move a final track.
    pub fn move_final_track(&mut self, from: usize, to: usize) {
        if from < self.final_tracks.len() && to < self.final_tracks.len() {
            let track = self.final_tracks.remove(from);
            self.final_tracks.insert(to, track);
        }
    }

    /// Remove a final track.
    pub fn remove_final_track(&mut self, idx: usize) {
        if idx < self.final_tracks.len() {
            self.final_tracks.remove(idx);
        }
    }

    /// Accept the layout and save to job.
    pub fn accept_layout(&mut self) {
        if let Some(job_idx) = self.manual_selection_job_idx {
            // Build ManualLayout from state
            let layout = ManualLayout {
                final_tracks: self
                    .final_tracks
                    .iter()
                    .map(|t| {
                        let track_type = match t.track_type.as_str() {
                            "video" => TrackType::Video,
                            "audio" => TrackType::Audio,
                            "subtitles" => TrackType::Subtitles,
                            _ => TrackType::Audio,
                        };

                        let mut entry = FinalTrackEntry::new(t.track_id, t.source_key.clone(), track_type);
                        entry.config.is_default = t.is_default;
                        entry.config.is_forced = t.is_forced;
                        entry.config.sync_to_source = Some(t.sync_to_source.clone());
                        if t.has_custom_name {
                            entry.config.custom_name = Some(t.custom_name.clone());
                        }
                        entry
                    })
                    .collect(),
                attachment_sources: self
                    .attachment_sources
                    .iter()
                    .filter(|(_, &checked)| checked)
                    .map(|(k, _)| k.clone())
                    .collect(),
                source_settings: HashMap::new(),
            };

            // Save to job queue
            let mut q = self.job_queue.lock().unwrap();
            q.set_layout(job_idx, layout);
            if let Err(e) = q.save() {
                tracing::warn!("Failed to save queue: {}", e);
            }

            self.job_queue_status = "Job configured".to_string();
        }
    }

    /// Accept track settings.
    pub fn accept_track_settings(&mut self) {
        if let Some(track_idx) = self.track_settings_idx {
            if let Some(track) = self.final_tracks.get_mut(track_idx) {
                track.has_custom_name = !self.track_settings.custom_name.is_empty();
                track.custom_name = self.track_settings.custom_name.clone();
            }
        }
    }
}

// =============================================================================
// Helper Functions
// =============================================================================

/// Clean up a file URL (from drag-drop) to a regular path.
fn clean_file_url(url: &str) -> String {
    let first_uri = url
        .lines()
        .map(|line| line.trim())
        .find(|line| !line.is_empty() && !line.starts_with('#'))
        .unwrap_or("");

    let path = if first_uri.starts_with("file://") {
        let without_prefix = &first_uri[7..];
        percent_decode(without_prefix)
    } else {
        first_uri.to_string()
    };

    path.trim().to_string()
}

/// Simple percent decoding for file paths.
fn percent_decode(input: &str) -> String {
    let mut result = String::with_capacity(input.len());
    let mut chars = input.chars().peekable();

    while let Some(c) = chars.next() {
        if c == '%' {
            let hex: String = chars.by_ref().take(2).collect();
            if hex.len() == 2 {
                if let Ok(byte) = u8::from_str_radix(&hex, 16) {
                    result.push(byte as char);
                    continue;
                }
            }
            result.push('%');
            result.push_str(&hex);
        } else {
            result.push(c);
        }
    }

    result
}

/// Track info from probing.
struct TrackInfo {
    track_id: usize,
    track_type: String,
    codec_id: String,
    summary: String,
    badges: String,
}

/// Probe tracks from a video file using mkvmerge -J.
fn probe_tracks(path: &PathBuf) -> Vec<TrackInfo> {
    let output = StdCommand::new("mkvmerge").arg("-J").arg(path).output();

    match output {
        Ok(output) if output.status.success() => {
            parse_mkvmerge_json(&String::from_utf8_lossy(&output.stdout))
        }
        _ => {
            vec![
                TrackInfo {
                    track_id: 0,
                    track_type: "video".to_string(),
                    codec_id: String::new(),
                    summary: "Video Track (probe failed)".to_string(),
                    badges: String::new(),
                },
                TrackInfo {
                    track_id: 1,
                    track_type: "audio".to_string(),
                    codec_id: String::new(),
                    summary: "Audio Track (probe failed)".to_string(),
                    badges: String::new(),
                },
            ]
        }
    }
}

/// Parse mkvmerge -J JSON output.
fn parse_mkvmerge_json(json_str: &str) -> Vec<TrackInfo> {
    let json: serde_json::Value = match serde_json::from_str(json_str) {
        Ok(v) => v,
        Err(_) => return Vec::new(),
    };

    let mut tracks = Vec::new();

    if let Some(track_array) = json.get("tracks").and_then(|t| t.as_array()) {
        for track in track_array {
            let track_type = track
                .get("type")
                .and_then(|t| t.as_str())
                .unwrap_or("unknown")
                .to_string();

            let codec = track
                .get("codec")
                .and_then(|c| c.as_str())
                .unwrap_or("Unknown");

            let properties = track.get("properties");

            let language = properties
                .and_then(|p| p.get("language"))
                .and_then(|l| l.as_str())
                .map(language_display)
                .unwrap_or_else(|| "und".to_string());

            let codec_id = properties
                .and_then(|p| p.get("codec_id"))
                .and_then(|c| c.as_str())
                .unwrap_or("")
                .to_string();

            let is_default = properties
                .and_then(|p| p.get("default_track"))
                .and_then(|d| d.as_bool())
                .unwrap_or(false);

            let is_forced = properties
                .and_then(|p| p.get("forced_track"))
                .and_then(|f| f.as_bool())
                .unwrap_or(false);

            let track_id = track
                .get("id")
                .and_then(|id| id.as_u64())
                .unwrap_or(0) as usize;

            let summary = match track_type.as_str() {
                "video" => {
                    let width = properties
                        .and_then(|p| p.get("pixel_dimensions"))
                        .and_then(|d| d.as_str())
                        .unwrap_or("");
                    format!("{}, {}", codec, width)
                }
                "audio" => {
                    let channels = properties
                        .and_then(|p| p.get("audio_channels"))
                        .and_then(|c| c.as_u64())
                        .unwrap_or(2);
                    let channel_str = channel_layout(channels as u8);
                    format!("{}, {}, {}", language, codec, channel_str)
                }
                "subtitles" => {
                    format!("{}, {}", language, codec)
                }
                _ => codec.to_string(),
            };

            let mut badges_list = Vec::new();
            if is_default {
                badges_list.push("Default");
            }
            if is_forced {
                badges_list.push("Forced");
            }

            tracks.push(TrackInfo {
                track_id,
                track_type,
                codec_id,
                summary,
                badges: badges_list.join(" | "),
            });
        }
    }

    tracks
}

/// Convert language code to display name.
fn language_display(code: &str) -> String {
    match code {
        "eng" => "English".to_string(),
        "jpn" => "Japanese".to_string(),
        "spa" => "Spanish".to_string(),
        "fre" | "fra" => "French".to_string(),
        "ger" | "deu" => "German".to_string(),
        "ita" => "Italian".to_string(),
        "por" => "Portuguese".to_string(),
        "rus" => "Russian".to_string(),
        "chi" | "zho" => "Chinese".to_string(),
        "kor" => "Korean".to_string(),
        "ara" => "Arabic".to_string(),
        "und" => "Undetermined".to_string(),
        _ => code.to_uppercase(),
    }
}

/// Convert channel count to display string.
fn channel_layout(channels: u8) -> String {
    match channels {
        1 => "Mono".to_string(),
        2 => "Stereo".to_string(),
        6 => "5.1".to_string(),
        8 => "7.1".to_string(),
        _ => format!("{} ch", channels),
    }
}

/// Run analysis only pipeline (async wrapper).
async fn run_analyze_only(
    job_spec: JobSpec,
    settings: Settings,
) -> Result<(Option<i64>, Option<i64>), String> {
    tokio::task::spawn_blocking(move || {
        let job_name = job_spec
            .sources
            .get("Source 1")
            .map(|p| {
                p.file_stem()
                    .map(|s| s.to_string_lossy().to_string())
                    .unwrap_or_else(|| "job".to_string())
            })
            .unwrap_or_else(|| "job".to_string());

        let timestamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs())
            .unwrap_or(0);

        let work_dir =
            PathBuf::from(&settings.paths.temp_root).join(format!("orch_{}_{}", job_name, timestamp));
        let output_dir = PathBuf::from(&settings.paths.output_folder);

        let log_config = LogConfig {
            compact: settings.logging.compact,
            progress_step: settings.logging.progress_step,
            error_tail: settings.logging.error_tail as usize,
            ..LogConfig::default()
        };

        let logger = match JobLogger::new(&job_name, &output_dir, log_config, None) {
            Ok(l) => std::sync::Arc::new(l),
            Err(e) => return Err(format!("Failed to create logger: {}", e)),
        };

        let ctx = Context::new(
            job_spec,
            settings,
            &job_name,
            work_dir,
            output_dir,
            logger.clone(),
        );

        let mut state = JobState::new(&job_name);
        let pipeline = Pipeline::new().with_step(AnalyzeStep::new());

        match pipeline.run(&ctx, &mut state) {
            Ok(_) => {
                let (delay2, delay3) = if let Some(ref analysis) = state.analysis {
                    let d2 = analysis.delays.source_delays_ms.get("Source 2").copied();
                    let d3 = analysis.delays.source_delays_ms.get("Source 3").copied();
                    (d2, d3)
                } else {
                    (None, None)
                };
                Ok((delay2, delay3))
            }
            Err(e) => Err(format!("Pipeline failed: {}", e)),
        }
    })
    .await
    .map_err(|e| format!("Task panicked: {}", e))?
}
