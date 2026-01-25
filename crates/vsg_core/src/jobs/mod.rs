//! Job queue and layout management.
//!
//! This module provides:
//! - `JobQueue`: In-memory queue of jobs with persistence to temp folder
//! - `JobQueueEntry`: Individual job with sources, status, and layout
//! - `ManualLayout`: User-configured track selection for a job
//! - `discovery`: Job discovery from source files (stub for now)

mod types;
mod queue;
mod discovery;
mod layout;

pub use types::{
    JobQueueEntry, JobQueueStatus, ManualLayout, FinalTrackEntry,
    TrackConfig, SourceCorrelationSettings,
};
pub use queue::JobQueue;
pub use discovery::discover_jobs;
pub use layout::LayoutManager;
