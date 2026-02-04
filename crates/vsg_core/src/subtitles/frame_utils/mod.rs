//! Frame utilities for video-verified sync mode.
//!
//! Provides video frame extraction, comparison, and timing utilities
//! for verifying subtitle timing against actual video frames.
//!
//! # Architecture
//!
//! This module is organized into focused submodules:
//!
//! - **types**: Core data structures (VideoProperties, settings, results)
//! - **timing**: Frame/time conversion functions (pure, deterministic)
//! - **hash**: Perceptual hashing (pHash, dHash, etc.)
//! - **compare**: Frame comparison (hash, SSIM, MSE)
//! - **properties**: Video property detection (ffprobe-based)
//! - **reader**: VideoReader with multiple backends (VapourSynth, FFmpeg)
//!
//! # Usage
//!
//! ```ignore
//! use vsg_core::subtitles::frame_utils::{
//!     open_video, detect_properties, compare_frames,
//!     VideoReaderConfig, ComparisonMethod, HashAlgorithm,
//! };
//!
//! // Open video
//! let config = VideoReaderConfig::default();
//! let reader = open_video(path, &config)?;
//!
//! // Get frames
//! let frame1 = reader.get_frame(100)?;
//! let frame2 = reader.get_frame(101)?;
//!
//! // Compare frames
//! let result = compare_frames(
//!     &frame1, &frame2,
//!     ComparisonMethod::Hash,
//!     HashAlgorithm::PHash,
//!     16, 12,
//! );
//! ```

pub mod compare;
pub mod hash;
pub mod properties;
pub mod reader;
pub mod timing;
pub mod types;

// ============================================================================
// Re-exports: Types
// ============================================================================

pub use types::{
    // Enums
    ComparisonMethod,
    ContentType,
    DeinterlaceMethod,
    FieldOrder,
    HashAlgorithm,
    IndexerBackend,
    InterlacedForceMode,
    SyncStrategy,
    // Structs
    CandidateResult,
    CheckpointMatch,
    FrameCompareResult,
    SequenceVerifyResult,
    VideoCompareResult,
    VideoProperties,
    VideoReaderConfig,
    VideoVerifiedSettings,
};

// ============================================================================
// Re-exports: Timing
// ============================================================================

pub use timing::{
    // Frame/time conversion
    frame_duration_ms,
    frame_to_time_aegisub,
    frame_to_time_floor,
    frame_to_time_middle,
    time_to_frame_aegisub,
    time_to_frame_floor,
    time_to_frame_middle,
    // Utilities
    fps_to_fraction,
    generate_frame_candidates,
    parse_fps_fraction,
    select_checkpoint_times,
};

// ============================================================================
// Re-exports: Hash
// ============================================================================

pub use hash::{
    compute_ahash,
    compute_blockhash,
    compute_dhash,
    compute_hash,
    compute_phash,
    create_hasher,
    hamming_distance,
    hash_to_hex,
    is_hash_match,
};

// ============================================================================
// Re-exports: Compare
// ============================================================================

pub use compare::{
    compare_frames,
    compare_frames_hash,
    compare_frames_mse,
    compare_frames_ssim,
    compute_mse,
    compute_ssim,
    recommended_threshold,
};

// ============================================================================
// Re-exports: Properties
// ============================================================================

pub use properties::{
    compare_video_properties,
    detect_fps,
    detect_properties,
    get_duration_ms,
    is_ffprobe_available,
};

// ============================================================================
// Re-exports: Reader
// ============================================================================

pub use reader::{
    available_backends,
    is_any_backend_available,
    open_video,
    FfmpegReader,
    VapourSynthReader,
    VideoReader,
};

// ============================================================================
// Convenience functions
// ============================================================================

/// Check if frame utilities are available.
///
/// Returns true if at least one video reader backend is available.
pub fn is_available() -> bool {
    is_any_backend_available()
}

/// Get a summary of available frame utilities.
pub fn availability_summary() -> String {
    let backends = available_backends();
    let ffprobe = is_ffprobe_available();

    let mut parts = Vec::new();

    if !backends.is_empty() {
        parts.push(format!("Video readers: {}", backends.join(", ")));
    } else {
        parts.push("Video readers: none".to_string());
    }

    parts.push(format!(
        "ffprobe: {}",
        if ffprobe { "available" } else { "not found" }
    ));

    parts.join("; ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_available() {
        // Just verify it doesn't panic
        let _available = is_available();
    }

    #[test]
    fn test_availability_summary() {
        let summary = availability_summary();
        assert!(summary.contains("Video readers:"));
        assert!(summary.contains("ffprobe:"));
    }

    #[test]
    fn test_timing_exports() {
        // Verify timing functions are exported
        let frame = time_to_frame_floor(1000.0, 23.976);
        let time = frame_to_time_floor(frame, 23.976);
        assert!((time - 1000.0).abs() < 50.0); // Within one frame
    }

    #[test]
    fn test_type_exports() {
        // Verify types are exported
        let _method = ComparisonMethod::Hash;
        let _algorithm = HashAlgorithm::PHash;
        let _config = VideoReaderConfig::default();
        let _settings = VideoVerifiedSettings::default();
    }
}
