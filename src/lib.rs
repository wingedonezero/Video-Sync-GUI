//! Video-Sync-GUI: Rust Rewrite
//!
//! A specialized desktop application for A/V timing analysis and lossless MKV remux
//! with predictable, auditable behavior.
//!
//! This is the Rust rewrite of the Python/PySide6 implementation, aiming for:
//! - Single binary distribution
//! - No runtime dependency management
//! - Better performance for audio/video processing
//! - Strong type safety

// Core modules
pub mod core;

// UI modules (will be enabled later when libcosmic is integrated)
// pub mod ui;

// Python bridge (optional, only for source separation)
// pub mod python;

// Re-exports
pub use core::config::AppConfig;
pub use core::models::{Delays, JobSpec, PlanItem, Track, TrackType};
