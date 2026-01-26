//! Job queue and layout management.
//!
//! This module provides:
//! - `JobQueue`: In-memory queue of jobs with persistence to temp folder
//! - `JobQueueEntry`: Individual job with sources, status, and layout
//! - `ManualLayout`: User-configured track selection for a job
//! - `SignatureGenerator`: Track/structure signatures for layout compatibility
//! - `discovery`: Job discovery from source files (stub for now)

mod types;
mod queue;
mod discovery;
mod layout;
mod signature;

pub use types::{
    JobQueueEntry, JobQueueStatus, ManualLayout, FinalTrackEntry,
    TrackConfig, SourceCorrelationSettings, SavedLayoutData,
};
pub use queue::JobQueue;
pub use discovery::discover_jobs;
pub use layout::{LayoutManager, generate_layout_id};
pub use signature::{
    SignatureGenerator, TrackSignature, StructureSignature,
    TrackSignatureInfo, tracks_to_signature_info,
};
