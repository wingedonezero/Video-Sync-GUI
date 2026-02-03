//! Audio analysis module for sync detection.
//!
//! This module provides functionality for analyzing audio sync offsets
//! between video sources using cross-correlation.
//!
//! # Architecture
//!
//! The analysis pipeline consists of pure functions that the orchestrator step
//! composes together:
//!
//! 1. **Audio Extraction** (`ffmpeg`): Extract audio from video files using FFmpeg,
//!    with optional SOXR high-quality resampling.
//!
//! 2. **Chunk Calculation** (`chunks`): Calculate evenly-distributed chunk positions
//!    across the scan range.
//!
//! 3. **Correlation** (`correlation`): Correlate audio chunks using various methods.
//!
//! 4. **Delay Selection** (`delay_selection`): Choose final delay from chunk results.
//!
//! 5. **Drift Detection** (`drift_detection`): Detect PAL drift, linear drift, or stepping.
//!
//! 6. **Stability Metrics** (`stability`): Calculate quality metrics from results.
//!
//! # Usage
//!
//! ```ignore
//! use vsg_core::analysis::{
//!     extract_full_audio, get_duration, calculate_chunk_positions,
//!     correlate_chunks, diagnose_drift, calculate_stability,
//!     ChunkConfig, CorrelationConfig, DriftDetectionConfig,
//! };
//!
//! // 1. Extract audio
//! let ref_audio = extract_full_audio(ref_path, 48000, true, None)?;
//! let other_audio = extract_full_audio(other_path, 48000, true, None)?;
//!
//! // 2. Calculate chunk positions
//! let duration = get_duration(ref_path)?;
//! let positions = calculate_chunk_positions(duration, &ChunkConfig::default());
//!
//! // 3. Correlate chunks
//! let method = create_from_enum(CorrelationMethod::Scc);
//! let chunks = correlate_chunks(&ref_audio, &other_audio, &positions, method.as_ref(), &config);
//!
//! // 4. Select delay
//! let accepted: Vec<_> = chunks.iter().filter(|c| c.accepted).cloned().collect();
//! let delay = get_selector(DelaySelectionMode::Mode).select(&accepted, &selector_config);
//!
//! // 5. Detect drift
//! let drift = diagnose_drift(&chunks, &DriftDetectionConfig::default(), framerate);
//!
//! // 6. Calculate stability
//! let stability = calculate_stability(&chunks, 5.0);
//! ```

mod analyzer;
mod chunks;
mod correlation;
pub mod delay_selection;
mod drift_detection;
mod ffmpeg;
pub mod filtering;
pub mod methods;
mod peak_fit;
mod stability;
mod tracks;
pub mod types;

// Re-export main types from types module
pub use types::{
    calculate_delay_std_dev, AnalysisError, AnalysisResult, AudioChunk, AudioData, ChunkResult,
    CorrelationResult, DelaySelection, SourceAnalysisResult, SourceStability,
};

// Re-export chunk calculation
pub use chunks::{calculate_chunk_positions, ChunkConfig};

// Re-export correlation functions
pub use correlation::{correlate_chunk_pair, correlate_chunks, CorrelationConfig};

// Re-export drift detection
pub use drift_detection::{diagnose_drift, DriftDetectionConfig, DriftDiagnosis, DriftType};

// Re-export stability calculation
pub use stability::{calculate_stability, calculate_std_dev, StabilityMetrics};

// Re-export FFmpeg functions
pub use ffmpeg::{
    extract_audio, extract_audio_segment, extract_full_audio, get_audio_container_delays_relative,
    get_duration, get_framerate, StreamDelay, DEFAULT_ANALYSIS_SAMPLE_RATE,
};

// Re-export filtering
pub use filtering::{apply_filter, FilterConfig, FilterType};

// Re-export peak fitting
pub use peak_fit::{find_and_fit_peak, fit_peak};

// Re-export track functions
pub use tracks::{find_track_by_language, get_audio_tracks, AudioTrack};

// Re-export method trait, implementations, and factory functions
pub use methods::{
    all_methods, create_from_enum, create_method, selected_methods, CorrelationMethod, Dtw,
    GccPhat, GccScot, Onset, Scc, Spectrogram, Whitened,
};

// Re-export delay selection
pub use delay_selection::{get_selector, DelaySelector, SelectorConfig};

// Keep Analyzer for backward compatibility during migration
// TODO: Remove after step refactor is complete
pub use analyzer::Analyzer;
