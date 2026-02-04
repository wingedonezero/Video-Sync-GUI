//! Video reader module.
//!
//! Provides frame-accurate video access through multiple backends:
//! - VapourSynth + FFMS2/BestSource (fastest, most accurate)
//! - FFmpeg subprocess (fallback, slower)
//!
//! # Usage
//!
//! ```ignore
//! use vsg_core::subtitles::frame_utils::reader::{open_video, VideoReaderConfig};
//!
//! let config = VideoReaderConfig::default();
//! let reader = open_video(path, &config)?;
//!
//! let frame = reader.get_frame(100)?;
//! let pts = reader.get_pts(100)?;
//! ```

mod ffmpeg;
mod vapoursynth;

use std::path::Path;

use image::DynamicImage;

pub use ffmpeg::FfmpegReader;
pub use vapoursynth::VapourSynthReader;

use super::types::VideoReaderConfig;
use crate::subtitles::error::FrameError;

/// Trait for video frame readers.
///
/// Implementations provide frame-accurate access to video files.
pub trait VideoReader: Send + Sync {
    /// Get frame by index (frame-accurate, preferred).
    ///
    /// # Arguments
    /// * `index` - Frame number (0-based)
    ///
    /// # Returns
    /// Frame as DynamicImage
    fn get_frame(&self, index: u32) -> Result<DynamicImage, FrameError>;

    /// Get frame at timestamp.
    ///
    /// Note: May have floating-point precision issues. Prefer get_frame() when possible.
    ///
    /// # Arguments
    /// * `time_ms` - Timestamp in milliseconds
    ///
    /// # Returns
    /// Frame as DynamicImage
    fn get_frame_at_time(&self, time_ms: f64) -> Result<DynamicImage, FrameError>;

    /// Get PTS (Presentation Time Stamp) for a frame in milliseconds.
    ///
    /// Essential for sub-frame precision in VFR content.
    ///
    /// # Arguments
    /// * `index` - Frame number
    ///
    /// # Returns
    /// PTS in milliseconds
    fn get_pts(&self, index: u32) -> Result<f64, FrameError>;

    /// Total frame count.
    fn frame_count(&self) -> u32;

    /// Video FPS.
    fn fps(&self) -> f64;

    /// Video width in pixels.
    fn width(&self) -> u32;

    /// Video height in pixels.
    fn height(&self) -> u32;

    /// Get the backend name.
    fn backend_name(&self) -> &str;

    /// Whether this reader supports deinterlacing.
    fn supports_deinterlace(&self) -> bool {
        false
    }
}

/// Open a video file with automatic backend selection.
///
/// Tries backends in order:
/// 1. VapourSynth (if available and video opens successfully)
/// 2. FFmpeg subprocess (fallback)
///
/// # Arguments
/// * `path` - Path to video file
/// * `config` - Reader configuration
///
/// # Returns
/// Box<dyn VideoReader> - The opened reader
///
/// # Logging
/// Logs backend selection with `[VideoReader]` prefix
pub fn open_video(path: &Path, config: &VideoReaderConfig) -> Result<Box<dyn VideoReader>, FrameError> {
    let filename = path
        .file_name()
        .map(|s| s.to_string_lossy())
        .unwrap_or_default();

    tracing::info!("[VideoReader] Opening video: {}", filename);

    // Try VapourSynth first (fastest, most accurate)
    if VapourSynthReader::is_available() {
        tracing::info!("[VideoReader] Attempting VapourSynth backend...");
        match VapourSynthReader::open(path, config) {
            Ok(reader) => {
                tracing::info!(
                    "[VideoReader] VapourSynth opened successfully ({} backend)",
                    config.indexer_backend.name()
                );
                tracing::info!(
                    "[VideoReader] Video: {}x{} @ {:.3} fps, {} frames",
                    reader.width(),
                    reader.height(),
                    reader.fps(),
                    reader.frame_count()
                );
                return Ok(Box::new(reader));
            }
            Err(e) => {
                tracing::warn!("[VideoReader] VapourSynth failed: {}", e);
                tracing::info!("[VideoReader] Falling back to FFmpeg...");
            }
        }
    } else {
        tracing::info!("[VideoReader] VapourSynth not available, using FFmpeg");
    }

    // Fallback to FFmpeg
    tracing::info!("[VideoReader] Attempting FFmpeg backend...");
    match FfmpegReader::open(path, config) {
        Ok(reader) => {
            tracing::info!("[VideoReader] FFmpeg opened successfully");
            tracing::info!(
                "[VideoReader] Video: {}x{} @ {:.3} fps, {} frames",
                reader.width(),
                reader.height(),
                reader.fps(),
                reader.frame_count()
            );
            Ok(Box::new(reader))
        }
        Err(e) => {
            tracing::error!("[VideoReader] FFmpeg failed: {}", e);
            Err(e)
        }
    }
}

/// Check if any video reader backend is available.
pub fn is_any_backend_available() -> bool {
    VapourSynthReader::is_available() || FfmpegReader::is_available()
}

/// Get list of available backends.
pub fn available_backends() -> Vec<&'static str> {
    let mut backends = Vec::new();

    if VapourSynthReader::is_available() {
        backends.push("vapoursynth");
    }
    if FfmpegReader::is_available() {
        backends.push("ffmpeg");
    }

    backends
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::subtitles::frame_utils::types::{DeinterlaceMethod, IndexerBackend};

    #[test]
    fn test_backend_availability_check() {
        // Just verify these don't panic
        let _vs_available = VapourSynthReader::is_available();
        let _ffmpeg_available = FfmpegReader::is_available();
        let _any_available = is_any_backend_available();
    }

    #[test]
    fn test_available_backends_list() {
        let backends = available_backends();
        // Should be a valid list (may be empty if nothing is installed)
        assert!(backends.len() <= 2);
    }

    #[test]
    fn test_video_reader_config_default() {
        let config = VideoReaderConfig::default();
        assert_eq!(config.deinterlace, DeinterlaceMethod::Auto);
        assert_eq!(config.indexer_backend, IndexerBackend::Ffms2);
    }
}
