//! Job queue and layout management.
//!
//! This module provides:
//! - `JobQueue`: In-memory queue of jobs with persistence to temp folder
//! - `JobQueueEntry`: Individual job with sources, status, and layout
//! - `ManualLayout`: User-configured track selection for a job
//! - `SignatureGenerator`: Track/structure signatures for layout compatibility
//! - `discovery`: Job discovery from source files (stub for now)

mod discovery;
mod layout;
mod queue;
mod signature;
mod types;

pub use discovery::discover_jobs;
pub use layout::{generate_layout_id, LayoutManager};
pub use queue::JobQueue;
pub use signature::{
    tracks_to_signature_info, SignatureGenerator, StructureSignature, TrackSignature,
    TrackSignatureInfo,
};
pub use types::{
    FinalTrackEntry, JobQueueEntry, JobQueueStatus, ManualLayout, SavedLayoutData, TrackConfig,
};
