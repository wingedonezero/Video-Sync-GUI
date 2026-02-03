//! Audio analysis module for sync detection.
//!
//! This module provides functionality for analyzing audio sync offsets
//! between video sources using cross-correlation.
//!
//! # Architecture
//!
//! The analysis pipeline consists of:
//!
//! 1. **Audio Extraction** (`ffmpeg`): Extract audio from video files using FFmpeg,
//!    with optional SOXR high-quality resampling.
//!
//! 2. **Correlation Methods** (`methods`): Modular correlation algorithms.
//!    Currently implements SCC (Standard Cross-Correlation) using FFT.
//!
//! 3. **Peak Fitting** (`peak_fit`): Quadratic interpolation for sub-sample
//!    accuracy in delay detection.
//!
//! 4. **Analyzer** (`analyzer`): Orchestrates the full pipeline, managing
//!    chunk-based analysis and result aggregation.
//!
//! # Usage
//!
//! ```ignore
//! use vsg_core::analysis::{Analyzer, SourceAnalysisResult};
//! use std::path::Path;
//!
//! let analyzer = Analyzer::new()
//!     .with_soxr(true)
//!     .with_peak_fit(true);
//!
//! let result = analyzer.analyze(
//!     Path::new("source1.mkv"),
//!     Path::new("source2.mkv"),
//!     "Source 2",
//! )?;
//!
//! println!("Delay: {:.2}ms", result.delay_ms);
//! ```

mod analyzer;
pub mod delay_selection;
mod ffmpeg;
pub mod filtering;
pub mod methods;
mod peak_fit;
mod tracks;
pub mod types;

// Re-export main types
pub use analyzer::Analyzer;
pub use ffmpeg::{
    extract_audio, extract_audio_segment, extract_full_audio, get_audio_container_delays_relative,
    get_duration, DEFAULT_ANALYSIS_SAMPLE_RATE,
};
pub use filtering::{apply_filter, FilterConfig, FilterType};
pub use peak_fit::{find_and_fit_peak, fit_peak};
pub use tracks::{find_track_by_language, get_audio_tracks, AudioTrack};
pub use types::{
    AnalysisError, AnalysisResult, AudioChunk, AudioData, ChunkResult, CorrelationResult,
    DelaySelection, SourceAnalysisResult,
};

// Re-export method trait, implementations, and factory functions
pub use methods::{
    all_methods, create_from_enum, create_method, selected_methods, CorrelationMethod, GccPhat,
    GccScot, Scc, Whitened,
};
