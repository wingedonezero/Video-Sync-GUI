//! Core engine modules
//!
//! This module contains all headless engine functionality:
//! - Configuration management
//! - Models (jobs, tracks, media)
//! - Analysis engines (audio correlation, videodiff)
//! - Extraction (tracks, attachments)
//! - Correction (linear, PAL, stepping)
//! - Subtitle processing
//! - Chapter handling
//! - Muxing (mkvmerge command builder)
//! - Pipeline orchestration

pub mod config;
pub mod models;
pub mod io;

// Analysis engines
pub mod analysis;

// Extraction
pub mod extraction;

// Correction
pub mod correction;

// Subtitles
pub mod subtitles;

// Chapters
pub mod chapters;

// Muxing
pub mod mux;

// Pipeline orchestration
pub mod orchestrator;

// Post-processing
pub mod postprocess;

// Pipeline components
pub mod pipeline_components;

// Job discovery and layout management
pub mod job_layouts;
