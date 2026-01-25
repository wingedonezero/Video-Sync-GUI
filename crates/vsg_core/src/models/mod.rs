//! Data models for Video Sync GUI.
//!
//! This module contains all core data structures used throughout the application:
//! - Enums for track types, analysis modes, job status
//! - Media structures (tracks, streams, attachments)
//! - Job structures (specs, plans, results)

mod enums;
mod jobs;
mod media;

// Re-export all public types
pub use enums::{
    AnalysisMode, CorrelationMethod, DelaySelectionMode, FilteringMethod, JobStatus, SnapMode,
    SyncMode, TrackType,
};
pub use jobs::{Delays, JobResult, JobSpec, MergePlan, PlanItem};
pub use media::{Attachment, StreamProps, Track};
