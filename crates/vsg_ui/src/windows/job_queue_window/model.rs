//! Job queue window state model

use std::collections::HashMap;
use std::path::PathBuf;

use vsg_core::jobs::{JobQueueEntry, JobQueueStatus};

/// Job queue window state
#[derive(Debug)]
pub struct JobQueueModel {
    /// Jobs in the queue
    pub jobs: Vec<JobDisplayEntry>,
    /// Selected job indices
    pub selected_indices: Vec<u32>,
    /// Whether clipboard has a layout
    pub has_clipboard: bool,
    /// Source job ID that layout was copied from
    pub clipboard_source: Option<String>,
}

/// Display entry for a job in the list
#[derive(Debug, Clone)]
pub struct JobDisplayEntry {
    /// The underlying job entry
    pub entry: JobQueueEntry,
    /// Display string for sources column
    pub sources_display: String,
    /// Tooltip with full paths
    pub sources_tooltip: String,
    /// Whether this job has validation warnings
    pub has_warnings: bool,
    /// Warning messages (for tooltip)
    pub warnings: Vec<String>,
}

impl JobDisplayEntry {
    /// Create a display entry from a job queue entry
    pub fn from_entry(entry: JobQueueEntry) -> Self {
        let sources_display = Self::format_sources_display(&entry.sources);
        let sources_tooltip = Self::format_sources_tooltip(&entry.sources);

        Self {
            entry,
            sources_display,
            sources_tooltip,
            has_warnings: false,
            warnings: Vec::new(),
        }
    }

    /// Format sources for display column
    fn format_sources_display(sources: &HashMap<String, PathBuf>) -> String {
        let mut parts: Vec<String> = Vec::new();

        for i in 1..=sources.len() {
            let key = format!("Source {}", i);
            if let Some(path) = sources.get(&key) {
                let name = path
                    .file_name()
                    .map(|n| n.to_string_lossy().to_string())
                    .unwrap_or_else(|| path.to_string_lossy().to_string());
                parts.push(name);
            }
        }

        parts.join(" + ")
    }

    /// Format sources for tooltip
    fn format_sources_tooltip(sources: &HashMap<String, PathBuf>) -> String {
        let mut lines: Vec<String> = Vec::new();

        for i in 1..=sources.len() {
            let key = format!("Source {}", i);
            if let Some(path) = sources.get(&key) {
                lines.push(format!("{}: {}", key, path.display()));
            }
        }

        lines.join("\n")
    }

    /// Get status display string
    pub fn status_display(&self) -> String {
        let base = self.entry.status.as_str();
        if self.has_warnings {
            format!("{} ⚠️", base)
        } else {
            base.to_string()
        }
    }
}

impl JobQueueModel {
    /// Create a new empty model
    pub fn new() -> Self {
        Self {
            jobs: Vec::new(),
            selected_indices: Vec::new(),
            has_clipboard: false,
            clipboard_source: None,
        }
    }

    /// Add jobs to the queue
    pub fn add_jobs(&mut self, jobs: Vec<JobQueueEntry>) {
        for job in jobs {
            self.jobs.push(JobDisplayEntry::from_entry(job));
        }
    }

    /// Remove jobs at the given indices
    pub fn remove_jobs(&mut self, indices: &[u32]) {
        // Sort descending to preserve indices during removal
        let mut sorted: Vec<u32> = indices.to_vec();
        sorted.sort_by(|a, b| b.cmp(a));

        for idx in sorted {
            if (idx as usize) < self.jobs.len() {
                self.jobs.remove(idx as usize);
            }
        }
        self.selected_indices.clear();
    }

    /// Move selected jobs up
    pub fn move_up(&mut self, indices: &[u32]) {
        let mut sorted: Vec<usize> = indices.iter().map(|&i| i as usize).collect();
        sorted.sort();

        for &idx in &sorted {
            if idx > 0 && idx < self.jobs.len() {
                self.jobs.swap(idx, idx - 1);
            }
        }

        // Update selection
        self.selected_indices = sorted
            .iter()
            .map(|&i| if i > 0 { (i - 1) as u32 } else { i as u32 })
            .collect();
    }

    /// Move selected jobs down
    pub fn move_down(&mut self, indices: &[u32]) {
        let mut sorted: Vec<usize> = indices.iter().map(|&i| i as usize).collect();
        sorted.sort_by(|a, b| b.cmp(a)); // Sort descending

        for &idx in &sorted {
            if idx + 1 < self.jobs.len() {
                self.jobs.swap(idx, idx + 1);
            }
        }

        // Update selection
        self.selected_indices = sorted
            .iter()
            .map(|&i| {
                if i + 1 < self.jobs.len() {
                    (i + 1) as u32
                } else {
                    i as u32
                }
            })
            .collect();
    }

    /// Clear all jobs
    pub fn clear(&mut self) {
        self.jobs.clear();
        self.selected_indices.clear();
    }

    /// Get job at index
    pub fn get_job(&self, index: usize) -> Option<&JobDisplayEntry> {
        self.jobs.get(index)
    }

    /// Get mutable job at index
    pub fn get_job_mut(&mut self, index: usize) -> Option<&mut JobDisplayEntry> {
        self.jobs.get_mut(index)
    }

    /// Get number of jobs
    pub fn job_count(&self) -> usize {
        self.jobs.len()
    }

    /// Get jobs that are configured (ready for processing)
    pub fn get_configured_job_ids(&self) -> Vec<String> {
        self.jobs
            .iter()
            .filter(|j| j.entry.status == JobQueueStatus::Configured)
            .map(|j| j.entry.id.clone())
            .collect()
    }

    /// Check if any job is selected
    pub fn has_selection(&self) -> bool {
        !self.selected_indices.is_empty()
    }

    /// Check if exactly one job is selected
    pub fn single_selection(&self) -> Option<usize> {
        if self.selected_indices.len() == 1 {
            Some(self.selected_indices[0] as usize)
        } else {
            None
        }
    }

    /// Check if the single selected job is configured (for copy)
    pub fn can_copy_layout(&self) -> bool {
        if let Some(idx) = self.single_selection() {
            if let Some(job) = self.jobs.get(idx) {
                return job.entry.status == JobQueueStatus::Configured;
            }
        }
        false
    }
}

impl Default for JobQueueModel {
    fn default() -> Self {
        Self::new()
    }
}
