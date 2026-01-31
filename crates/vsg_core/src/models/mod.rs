//! Data models for Video Sync GUI.
//!
//! This module contains all core data structures used throughout the application:
//! - Enums for track types, analysis modes, job status
//! - Media structures (tracks, streams, attachments)
//! - Job structures (specs, plans, results)
//! - Source identification (SourceIndex)

mod enums;
mod jobs;
mod media;
mod source_index;

// Re-export all public types
pub use enums::{
    AnalysisMode, CorrelationMethod, DelaySelectionMode, FilteringMethod, JobStatus, SnapMode,
    SyncMode, TrackType,
};
pub use jobs::{Delays, JobResult, JobSpec, MergePlan, PlanItem, SourceDelay};
pub use media::{Attachment, StreamProps, Track};
pub use source_index::SourceIndex;
