//! Frame utilities for video-verified sync mode.
//!
//! Provides video frame extraction and comparison for verifying subtitle timing.
//!
//! # Components
//!
//! - **reader**: FFmpeg-based frame extraction
//! - **hash**: Perceptual hashing (pHash, dHash, etc.)
//! - **properties**: Video property detection (FPS, duration, interlacing)
//!
//! # Status
//!
//! This module is a placeholder for future implementation.
//! The video-verified sync mode will use these utilities for frame matching.

// Future submodules:
// mod reader;
// mod hash;
// mod properties;

/// Check if frame utilities are available.
///
/// Returns true if FFmpeg is installed and accessible.
pub fn is_available() -> bool {
    // Check for FFmpeg
    std::process::Command::new("ffmpeg")
        .arg("-version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

/// Video properties detected from a file.
#[derive(Debug, Clone, Default)]
pub struct VideoProperties {
    /// Frames per second.
    pub fps: Option<f64>,
    /// Duration in milliseconds.
    pub duration_ms: Option<f64>,
    /// Width in pixels.
    pub width: Option<u32>,
    /// Height in pixels.
    pub height: Option<u32>,
    /// Content type (progressive, interlaced, telecine).
    pub content_type: Option<String>,
}

/// Detect video properties from a file.
///
/// Uses FFprobe to extract video metadata.
pub fn detect_properties(_path: &std::path::Path) -> Result<VideoProperties, String> {
    // TODO: Implement FFprobe-based detection
    Err("Not implemented".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_available() {
        // This just checks if the function runs without panic
        let _available = is_available();
    }
}
