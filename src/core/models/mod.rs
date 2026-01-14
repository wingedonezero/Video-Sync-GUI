//! Core data models
//!
//! This module contains all the data structures used throughout the pipeline:
//! - Track types and enumerations
//! - Media stream properties
//! - Job specifications and plans
//! - Delay information
//! - Settings models

pub mod enums;
pub mod media;
pub mod jobs;
pub mod settings;
pub mod converters;
pub mod results;

// Re-exports for convenience
pub use enums::TrackType;
pub use media::{StreamProps, Track};
pub use jobs::{Delays, JobSpec, MergePlan, PlanItem};
pub use settings::AppSettings;
