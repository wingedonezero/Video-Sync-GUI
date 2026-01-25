//! Job queue handlers.

use std::collections::HashMap;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use iced::window;
use iced::Task;

use vsg_core::jobs::discover_jobs;

use crate::app::{App, Message};

impl App {
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

    /// Handle job row click - with double-click detection.
    /// Returns true if this was a double-click.
    pub fn handle_job_row_clicked(&mut self, idx: usize) -> bool {
        let now = Instant::now();
        let double_click_threshold = Duration::from_millis(400);

        // Check for double-click
        let is_double_click = match (self.last_clicked_job_idx, self.last_click_time) {
            (Some(last_idx), Some(last_time)) => {
                last_idx == idx && now.duration_since(last_time) < double_click_threshold
            }
            _ => false,
        };

        if is_double_click {
            // Reset click tracking
            self.last_clicked_job_idx = None;
            self.last_click_time = None;
            // Will return true - caller should open manual selection
            true
        } else {
            // Single click - select this row (clear previous selection)
            self.selected_job_indices.clear();
            self.selected_job_indices.push(idx);

            // Track for potential double-click
            self.last_clicked_job_idx = Some(idx);
            self.last_click_time = Some(now);
            false
        }
    }

    /// Handle file dropped on a window.
    pub fn handle_file_dropped(&mut self, window_id: window::Id, path: PathBuf) {
        let path_str = path.to_string_lossy().to_string();

        // Determine which window received the drop
        if window_id == self.main_window_id {
            // Drop on main window - fill first empty source
            if self.source1_path.is_empty() {
                self.source1_path = path_str.clone();
                self.append_log(&format!("Source 1: {}", path_str));
            } else if self.source2_path.is_empty() {
                self.source2_path = path_str.clone();
                self.append_log(&format!("Source 2: {}", path_str));
            } else if self.source3_path.is_empty() {
                self.source3_path = path_str.clone();
                self.append_log(&format!("Source 3: {}", path_str));
            } else {
                self.append_log("All source slots are full");
            }
        } else if self.add_job_window_id == Some(window_id) {
            // Drop on Add Job window - fill first empty source
            for (idx, source) in self.add_job_sources.iter_mut().enumerate() {
                if source.is_empty() {
                    *source = path_str.clone();
                    self.append_log(&format!("Add Job Source {}: {}", idx + 1, path_str));
                    break;
                }
            }
        } else if self.job_queue_window_id == Some(window_id) {
            // Drop on Job Queue - auto-add as new job source
            // For now, just log it - proper handling would discover jobs
            self.append_log(&format!("File dropped on Job Queue: {}", path_str));
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
            Message::JobsAdded,
        )
    }
}
