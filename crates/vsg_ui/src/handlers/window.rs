//! Window management handlers.

use iced::window;
use iced::{Size, Task};

use crate::app::{App, Message, WindowKind, LANGUAGE_CODES};

impl App {
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
            size: Size::new(900.0, 700.0),
            resizable: true,
            decorations: true,
            ..Default::default()
        };

        let (id, open_task) = window::open(settings);
        self.window_map.insert(id, WindowKind::Settings);
        self.settings_window_id = Some(id);

        open_task.map(|_| Message::Noop)
    }

    /// Close the settings window.
    pub fn close_settings_window(&mut self) -> Task<Message> {
        if let Some(id) = self.settings_window_id.take() {
            self.window_map.remove(&id);
            self.pending_settings = None;
            return window::close(id);
        }
        Task::none()
    }

    /// Open the job queue window.
    /// Clears any existing queue and layouts to start fresh (prevents stale data from crashes).
    pub fn open_job_queue_window(&mut self) -> Task<Message> {
        if self.job_queue_window_id.is_some() {
            return Task::none();
        }

        // Fresh start: Clear any existing queue and layouts
        // This prevents loading stale data from crashes or abandoned sessions
        {
            let mut q = self.job_queue.lock().unwrap();
            q.clear();
            if let Err(e) = q.save() {
                tracing::warn!("Failed to clear queue: {}", e);
            }
        }
        {
            let lm = self.layout_manager.lock().unwrap();
            if let Err(e) = lm.cleanup_all() {
                tracing::warn!("Failed to cleanup layouts: {}", e);
            }
        }

        self.append_log("Opening job queue...");

        let settings = window::Settings {
            size: Size::new(1100.0, 600.0),
            resizable: true,
            decorations: true,
            ..Default::default()
        };

        let (id, open_task) = window::open(settings);
        self.window_map.insert(id, WindowKind::JobQueue);
        self.job_queue_window_id = Some(id);

        open_task.map(|_| Message::Noop)
    }

    /// Close the job queue window.
    /// If NOT processing, clears queue and layouts (user cancelled).
    /// If processing, keeps data intact (jobs are being used by batch processor).
    pub fn close_job_queue_window(&mut self) -> Task<Message> {
        if let Some(id) = self.job_queue_window_id.take() {
            self.window_map.remove(&id);

            // Cleanup: Clear job queue UI state
            self.selected_job_indices.clear();
            self.job_queue_status.clear();
            self.last_clicked_job_idx = None;
            self.last_click_time = None;

            // Only clear queue and layouts if NOT processing
            // (If processing, the batch processor needs the data)
            if !self.is_processing {
                // User cancelled or closed without processing - discard everything
                {
                    let mut q = self.job_queue.lock().unwrap();
                    q.clear();
                    if let Err(e) = q.save() {
                        tracing::warn!("Failed to clear queue on close: {}", e);
                    }
                }
                {
                    let lm = self.layout_manager.lock().unwrap();
                    if let Err(e) = lm.cleanup_all() {
                        tracing::warn!("Failed to cleanup layouts on close: {}", e);
                    }
                }
                self.append_log("Job Queue closed (cancelled - queue cleared).");
            } else {
                self.append_log("Job Queue closed (processing started).");
            }

            return window::close(id);
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
            decorations: true,
            ..Default::default()
        };

        let (id, open_task) = window::open(settings);
        self.window_map.insert(id, WindowKind::AddJob);
        self.add_job_window_id = Some(id);

        open_task.map(|_| Message::Noop)
    }

    /// Close the add job window.
    pub fn close_add_job_window(&mut self) -> Task<Message> {
        if let Some(id) = self.add_job_window_id.take() {
            self.window_map.remove(&id);
            return window::close(id);
        }
        Task::none()
    }

    /// Open the manual selection window for a job.
    pub fn open_manual_selection_window(&mut self, job_idx: usize) -> Task<Message> {
        if self.manual_selection_window_id.is_some() {
            return Task::none();
        }

        // Get job info
        let (sources, _job_name) = {
            let q = self.job_queue.lock().unwrap();
            match q.get(job_idx) {
                Some(job) => (job.sources.clone(), job.name.clone()),
                None => {
                    self.job_queue_status = "Job not found".to_string();
                    return Task::none();
                }
            }
        };

        // Populate source groups (must happen before loading layout)
        self.populate_source_groups(&sources);
        self.manual_selection_job_idx = Some(job_idx);
        self.final_tracks.clear();
        self.attachment_sources.clear();

        // Try to load existing layout from disk
        // If no layout exists, default to Source 1 for attachments
        if !self.load_existing_layout(&sources) {
            self.attachment_sources.insert("Source 1".to_string(), true);
        }

        let settings = window::Settings {
            size: Size::new(1200.0, 800.0),
            resizable: true,
            decorations: true,
            ..Default::default()
        };

        let (id, open_task) = window::open(settings);
        self.window_map.insert(id, WindowKind::ManualSelection(job_idx));
        self.manual_selection_window_id = Some(id);

        open_task.map(|_| Message::Noop)
    }

    /// Close the manual selection window.
    /// Cleans up all manual selection state (like Qt's cleanup on cancel)
    pub fn close_manual_selection_window(&mut self) -> Task<Message> {
        if let Some(id) = self.manual_selection_window_id.take() {
            self.window_map.remove(&id);
            self.manual_selection_job_idx = None;
            self.source_groups.clear();
            self.final_tracks.clear();
            self.attachment_sources.clear();
            self.external_subtitles.clear();
            self.manual_selection_info.clear();

            // TODO: When temp file handling is implemented, clean up:
            // - Style editor preview files
            // - OCR preview files for this job
            // - Extracted subtitle files

            return window::close(id);
        }
        Task::none()
    }

    /// Open the track settings window.
    pub fn open_track_settings_window(&mut self, track_idx: usize) -> Task<Message> {
        tracing::debug!(
            "open_track_settings_window called: track_idx={}, window_id_is_some={}",
            track_idx,
            self.track_settings_window_id.is_some()
        );

        if self.track_settings_window_id.is_some() {
            tracing::debug!("Track settings window already open, returning early");
            return Task::none();
        }

        // Load all settings from the specific track entry
        if let Some(track) = self.final_tracks.get(track_idx) {
            self.track_settings.track_type = track.track_type.clone();
            self.track_settings.codec_id = track.codec_id.clone();
            self.track_settings.custom_lang = track.custom_lang.clone();
            self.track_settings.custom_name = track.custom_name.clone();
            self.track_settings.perform_ocr = track.perform_ocr;
            self.track_settings.convert_to_ass = track.convert_to_ass;
            self.track_settings.rescale = track.rescale;
            self.track_settings.size_multiplier_pct = track.size_multiplier_pct;
            self.track_settings.sync_exclusion_styles = track.sync_exclusion_styles.clone();
            self.track_settings.sync_exclusion_mode = track.sync_exclusion_mode;
            self.track_settings_idx = Some(track_idx);

            // Set language picker index from custom_lang or original_lang
            let lang_to_find = track.custom_lang.as_deref().or(track.original_lang.as_deref()).unwrap_or("und");
            self.track_settings.selected_language_idx = LANGUAGE_CODES
                .iter()
                .position(|&code| code == lang_to_find)
                .unwrap_or(0);
        }

        let settings = window::Settings {
            size: Size::new(500.0, 450.0),
            resizable: false,
            decorations: true,
            ..Default::default()
        };

        let (id, open_task) = window::open(settings);
        self.window_map.insert(id, WindowKind::TrackSettings(track_idx));
        self.track_settings_window_id = Some(id);

        open_task.map(|_| Message::Noop)
    }

    /// Close the track settings window.
    pub fn close_track_settings_window(&mut self) -> Task<Message> {
        tracing::debug!(
            "close_track_settings_window called: window_id_is_some={}",
            self.track_settings_window_id.is_some()
        );

        if let Some(id) = self.track_settings_window_id.take() {
            self.window_map.remove(&id);
            self.track_settings_idx = None;
            tracing::debug!("Track settings window closed, ID cleared");
            return window::close(id);
        }
        Task::none()
    }

    /// Handle window closed event (e.g., user clicked X button).
    pub fn handle_window_closed(&mut self, id: window::Id) -> Task<Message> {
        if let Some(window_kind) = self.window_map.remove(&id) {
            match window_kind {
                WindowKind::Settings => {
                    self.settings_window_id = None;
                    self.pending_settings = None;
                }
                WindowKind::JobQueue => {
                    self.job_queue_window_id = None;

                    // Clear UI state
                    self.selected_job_indices.clear();
                    self.job_queue_status.clear();
                    self.last_clicked_job_idx = None;
                    self.last_click_time = None;

                    // Only clear queue and layouts if NOT processing
                    if !self.is_processing {
                        {
                            let mut q = self.job_queue.lock().unwrap();
                            q.clear();
                            let _ = q.save();
                        }
                        {
                            let lm = self.layout_manager.lock().unwrap();
                            let _ = lm.cleanup_all();
                        }
                        self.append_log("Job Queue closed (cancelled - queue cleared).");
                    }
                }
                WindowKind::AddJob => {
                    self.add_job_window_id = None;
                }
                WindowKind::ManualSelection(_) => {
                    self.manual_selection_window_id = None;
                    self.manual_selection_job_idx = None;
                }
                WindowKind::TrackSettings(_) => {
                    self.track_settings_window_id = None;
                    self.track_settings_idx = None;
                }
                _ => {}
            }
        }
        Task::none()
    }

    /// Handle window opened event.
    pub fn handle_window_opened(&mut self, window_kind: WindowKind, id: window::Id) -> Task<Message> {
        self.window_map.insert(id, window_kind);
        Task::none()
    }
}
