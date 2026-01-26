//! Job queue state management with persistence.

use std::fs;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use super::types::{JobQueueEntry, JobQueueStatus, ManualLayout};

/// Persistent queue state (saved to queue.json).
#[derive(Debug, Clone, Serialize, Deserialize)]
struct QueueState {
    /// Queue format version.
    version: u32,
    /// Jobs in queue order.
    jobs: Vec<JobQueueEntry>,
}

impl Default for QueueState {
    fn default() -> Self {
        Self {
            version: 1,
            jobs: Vec::new(),
        }
    }
}

/// Clipboard data for copy/paste between jobs.
#[derive(Debug, Clone)]
pub struct LayoutClipboard {
    /// The copied layout.
    pub layout: ManualLayout,
    /// Job ID the layout was copied from.
    pub source_job_id: String,
    /// Layout ID (for signature lookup).
    pub layout_id: String,
}

/// In-memory job queue with persistence to temp folder.
#[derive(Debug)]
pub struct JobQueue {
    /// Jobs in queue order.
    jobs: Vec<JobQueueEntry>,
    /// Path to queue.json for persistence.
    queue_file: PathBuf,
    /// Layout clipboard (for copy/paste between jobs).
    clipboard: Option<LayoutClipboard>,
}

impl JobQueue {
    /// Create a new queue with persistence to the given temp folder.
    pub fn new(temp_folder: &Path) -> Self {
        let queue_file = temp_folder.join("queue.json");

        // Try to load existing queue
        let jobs = if queue_file.exists() {
            match fs::read_to_string(&queue_file) {
                Ok(content) => {
                    match serde_json::from_str::<QueueState>(&content) {
                        Ok(state) => {
                            tracing::info!("Loaded {} jobs from queue.json", state.jobs.len());
                            state.jobs
                        }
                        Err(e) => {
                            tracing::warn!("Failed to parse queue.json: {}", e);
                            Vec::new()
                        }
                    }
                }
                Err(e) => {
                    tracing::warn!("Failed to read queue.json: {}", e);
                    Vec::new()
                }
            }
        } else {
            Vec::new()
        };

        Self {
            jobs,
            queue_file,
            clipboard: None,
        }
    }

    /// Create a queue without persistence (for testing).
    pub fn in_memory() -> Self {
        Self {
            jobs: Vec::new(),
            queue_file: PathBuf::new(),
            clipboard: None,
        }
    }

    /// Persist queue to disk.
    pub fn save(&self) -> Result<(), std::io::Error> {
        if self.queue_file.as_os_str().is_empty() {
            return Ok(()); // In-memory queue, nothing to save
        }

        // Ensure parent directory exists
        if let Some(parent) = self.queue_file.parent() {
            fs::create_dir_all(parent)?;
        }

        let state = QueueState {
            version: 1,
            jobs: self.jobs.clone(),
        };

        let json = serde_json::to_string_pretty(&state)
            .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

        // Write atomically via temp file
        let temp_file = self.queue_file.with_extension("json.tmp");
        fs::write(&temp_file, &json)?;
        fs::rename(&temp_file, &self.queue_file)?;

        tracing::debug!("Saved {} jobs to queue.json", self.jobs.len());
        Ok(())
    }

    /// Get all jobs.
    pub fn jobs(&self) -> &[JobQueueEntry] {
        &self.jobs
    }

    /// Get a job by index.
    pub fn get(&self, index: usize) -> Option<&JobQueueEntry> {
        self.jobs.get(index)
    }

    /// Get a mutable job by index.
    pub fn get_mut(&mut self, index: usize) -> Option<&mut JobQueueEntry> {
        self.jobs.get_mut(index)
    }

    /// Get a job by ID.
    pub fn get_by_id(&self, id: &str) -> Option<&JobQueueEntry> {
        self.jobs.iter().find(|j| j.id == id)
    }

    /// Get a mutable job by ID.
    pub fn get_by_id_mut(&mut self, id: &str) -> Option<&mut JobQueueEntry> {
        self.jobs.iter_mut().find(|j| j.id == id)
    }

    /// Number of jobs in queue.
    pub fn len(&self) -> usize {
        self.jobs.len()
    }

    /// Check if queue is empty.
    pub fn is_empty(&self) -> bool {
        self.jobs.is_empty()
    }

    /// Add a job to the queue.
    pub fn add(&mut self, job: JobQueueEntry) {
        self.jobs.push(job);
    }

    /// Add multiple jobs to the queue.
    pub fn add_all(&mut self, jobs: Vec<JobQueueEntry>) {
        self.jobs.extend(jobs);
    }

    /// Remove a job by index.
    pub fn remove(&mut self, index: usize) -> Option<JobQueueEntry> {
        if index < self.jobs.len() {
            Some(self.jobs.remove(index))
        } else {
            None
        }
    }

    /// Remove jobs by indices (in descending order to preserve indices).
    pub fn remove_indices(&mut self, mut indices: Vec<usize>) {
        indices.sort_by(|a, b| b.cmp(a)); // Sort descending
        for idx in indices {
            if idx < self.jobs.len() {
                self.jobs.remove(idx);
            }
        }
    }

    /// Move a job from one position to another.
    pub fn move_job(&mut self, from: usize, to: usize) {
        if from < self.jobs.len() && to < self.jobs.len() && from != to {
            let job = self.jobs.remove(from);
            self.jobs.insert(to, job);
        }
    }

    /// Move selected jobs up by one position.
    pub fn move_up(&mut self, indices: &[usize]) {
        let mut sorted: Vec<usize> = indices.to_vec();
        sorted.sort();

        for &idx in &sorted {
            if idx > 0 && idx < self.jobs.len() {
                self.jobs.swap(idx, idx - 1);
            }
        }
    }

    /// Move selected jobs down by one position.
    pub fn move_down(&mut self, indices: &[usize]) {
        let mut sorted: Vec<usize> = indices.to_vec();
        sorted.sort_by(|a, b| b.cmp(a)); // Sort descending

        for &idx in &sorted {
            if idx + 1 < self.jobs.len() {
                self.jobs.swap(idx, idx + 1);
            }
        }
    }

    /// Set layout for a job.
    pub fn set_layout(&mut self, index: usize, layout: ManualLayout) {
        if let Some(job) = self.jobs.get_mut(index) {
            job.layout = Some(layout);
            job.status = JobQueueStatus::Configured;
        }
    }

    /// Copy layout from a job to clipboard.
    pub fn copy_layout(&mut self, index: usize) -> bool {
        if let Some(job) = self.jobs.get(index) {
            if let Some(ref layout) = job.layout {
                self.clipboard = Some(LayoutClipboard {
                    layout: layout.clone(),
                    source_job_id: job.id.clone(),
                    layout_id: job.layout_id.clone(),
                });
                return true;
            }
        }
        false
    }

    /// Paste layout from clipboard to selected jobs.
    /// Returns the number of jobs that were updated.
    pub fn paste_layout(&mut self, indices: &[usize]) -> usize {
        let Some(ref clipboard) = self.clipboard else {
            return 0;
        };

        let layout_to_paste = clipboard.layout.clone();
        let mut count = 0;

        for &idx in indices {
            if let Some(job) = self.jobs.get_mut(idx) {
                job.layout = Some(layout_to_paste.clone());
                job.status = JobQueueStatus::Configured;
                count += 1;
            }
        }
        count
    }

    /// Get clipboard info for display (source job ID).
    pub fn clipboard_source(&self) -> Option<&str> {
        self.clipboard.as_ref().map(|c| c.source_job_id.as_str())
    }

    /// Check if clipboard has a layout.
    pub fn has_clipboard(&self) -> bool {
        self.clipboard.is_some()
    }

    /// Clear the queue.
    pub fn clear(&mut self) {
        self.jobs.clear();
    }

    /// Get jobs ready for processing (status == Configured).
    pub fn jobs_ready(&self) -> Vec<&JobQueueEntry> {
        self.jobs
            .iter()
            .filter(|j| j.status == JobQueueStatus::Configured)
            .collect()
    }

    /// Update job status.
    pub fn set_status(&mut self, index: usize, status: JobQueueStatus) {
        if let Some(job) = self.jobs.get_mut(index) {
            job.status = status;
        }
    }

    /// Mark job as failed with error message.
    pub fn set_error(&mut self, index: usize, error: String) {
        if let Some(job) = self.jobs.get_mut(index) {
            job.status = JobQueueStatus::Error;
            job.error_message = Some(error);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn make_job(id: &str) -> JobQueueEntry {
        let mut sources = HashMap::new();
        sources.insert("Source 1".to_string(), PathBuf::from("/test/a.mkv"));
        sources.insert("Source 2".to_string(), PathBuf::from("/test/b.mkv"));
        JobQueueEntry::new(id.to_string(), format!("Job {}", id), sources)
    }

    #[test]
    fn queue_add_remove() {
        let mut queue = JobQueue::in_memory();
        queue.add(make_job("1"));
        queue.add(make_job("2"));

        assert_eq!(queue.len(), 2);

        queue.remove(0);
        assert_eq!(queue.len(), 1);
        assert_eq!(queue.get(0).unwrap().id, "2");
    }

    #[test]
    fn queue_move() {
        let mut queue = JobQueue::in_memory();
        queue.add(make_job("1"));
        queue.add(make_job("2"));
        queue.add(make_job("3"));

        queue.move_job(0, 2);
        assert_eq!(queue.get(0).unwrap().id, "2");
        assert_eq!(queue.get(1).unwrap().id, "3");
        assert_eq!(queue.get(2).unwrap().id, "1");
    }

    #[test]
    fn queue_copy_paste_layout() {
        let mut queue = JobQueue::in_memory();
        queue.add(make_job("1"));
        queue.add(make_job("2"));

        // Set layout on first job
        let layout = ManualLayout::new();
        queue.set_layout(0, layout);
        assert_eq!(queue.get(0).unwrap().status, JobQueueStatus::Configured);

        // Copy and paste
        assert!(queue.copy_layout(0));
        assert!(queue.has_clipboard());

        let count = queue.paste_layout(&[1]);
        assert_eq!(count, 1);
        assert_eq!(queue.get(1).unwrap().status, JobQueueStatus::Configured);
    }
}
