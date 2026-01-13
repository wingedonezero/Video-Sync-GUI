//! Job Queue Dialog
//!
//! Manages the queue of merge jobs

use cosmic::widget::{self, text};
use cosmic::iced::Length;
use cosmic::Element;
use std::path::PathBuf;

/// A job in the queue
#[derive(Debug, Clone)]
pub struct Job {
    /// Unique job ID
    pub id: u64,
    /// Reference file path
    pub reference: PathBuf,
    /// Secondary file path
    pub secondary: PathBuf,
    /// Optional tertiary file path
    pub tertiary: Option<PathBuf>,
    /// Job status
    pub status: JobStatus,
    /// Output path (if complete)
    pub output: Option<PathBuf>,
}

/// Status of a job
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum JobStatus {
    Pending,
    Running { progress: u8 },
    Complete,
    Failed(String),
}

/// Job queue dialog state
#[derive(Debug, Clone, Default)]
pub struct JobQueueDialog {
    /// List of jobs
    pub jobs: Vec<Job>,
    /// Currently selected job index
    pub selected: Option<usize>,
    /// Whether batch is running
    pub batch_running: bool,
}

/// Messages for the job queue dialog
#[derive(Debug, Clone)]
pub enum JobQueueMessage {
    /// Add a new job
    AddJob,
    /// Remove selected job
    RemoveJob(u64),
    /// Start processing all jobs
    StartBatch,
    /// Stop batch processing
    StopBatch,
    /// Select a job
    SelectJob(usize),
    /// Clear completed jobs
    ClearCompleted,
    /// Close dialog
    Close,
}

impl JobQueueDialog {
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a job to the queue
    pub fn add_job(&mut self, reference: PathBuf, secondary: PathBuf, tertiary: Option<PathBuf>) {
        let id = self.jobs.len() as u64 + 1;
        self.jobs.push(Job {
            id,
            reference,
            secondary,
            tertiary,
            status: JobStatus::Pending,
            output: None,
        });
    }

    /// View the job queue dialog
    pub fn view(&self) -> Element<JobQueueMessage> {
        // Toolbar
        let mut add_job_btn = widget::button::standard("Add Job...");
        add_job_btn = add_job_btn.on_press(JobQueueMessage::AddJob);
        add_job_btn = add_job_btn.class(cosmic::theme::Button::Suggested);

        let start_batch_btn = if !self.batch_running && !self.jobs.is_empty() {
            widget::button::standard("Start Batch")
                .on_press(JobQueueMessage::StartBatch)
        } else {
            widget::button::standard("Start Batch")
        };

        let stop_btn = if self.batch_running {
            widget::button::standard("Stop")
                .on_press(JobQueueMessage::StopBatch)
        } else {
            widget::button::standard("Stop")
        };

        let toolbar = widget::row()
            .push(add_job_btn)
            .push(start_batch_btn)
            .push(stop_btn)
            .push(widget::horizontal_space())
            .push(widget::button::standard("Clear Completed")
                .on_press(JobQueueMessage::ClearCompleted))
            .spacing(8);

        // Job list
        let job_list: Element<JobQueueMessage> = if self.jobs.is_empty() {
            text("No jobs in queue. Click 'Add Job' to get started.").into()
        } else {
            let items: Vec<Element<JobQueueMessage>> = self.jobs
                .iter()
                .enumerate()
                .map(|(idx, job)| self.view_job_row(idx, job))
                .collect();

            widget::column().extend(items).spacing(4).into()
        };

        // Bottom buttons
        let bottom_row = widget::row()
            .push(widget::horizontal_space())
            .push(widget::button::standard("Close")
                .on_press(JobQueueMessage::Close));

        widget::column()
            .push(toolbar)
            .push(widget::scrollable(job_list)
                .height(Length::Fill))
            .push(bottom_row)
            .spacing(12)
            .into()
    }

    fn view_job_row(&self, idx: usize, job: &Job) -> Element<JobQueueMessage> {
        let status_text = match &job.status {
            JobStatus::Pending => "Pending".to_string(),
            JobStatus::Running { progress } => format!("Running {}%", progress),
            JobStatus::Complete => "Complete".to_string(),
            JobStatus::Failed(e) => format!("Failed: {}", e),
        };

        let ref_name = job.reference
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| "?".to_string());

        let is_selected = self.selected == Some(idx);

        widget::row()
            .push(text(ref_name).width(Length::Fill))
            .push(text(status_text).width(Length::Fixed(150.0)))
            .push(widget::button::icon(widget::icon::from_name("user-trash-symbolic"))
                .on_press(JobQueueMessage::RemoveJob(job.id)))
            .spacing(8)
            .into()
    }
}
