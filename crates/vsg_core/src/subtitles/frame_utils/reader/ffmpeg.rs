//! FFmpeg subprocess-based video reader.
//!
//! Fallback reader that uses FFmpeg to extract frames via subprocess.
//! Slower than VapourSynth but works everywhere FFmpeg is installed.

use std::io::Cursor;
use std::path::{Path, PathBuf};
use std::process::Command;

use image::DynamicImage;

use super::VideoReader;
use crate::subtitles::error::FrameError;
use crate::subtitles::frame_utils::properties::detect_properties;
use crate::subtitles::frame_utils::types::VideoReaderConfig;

/// FFmpeg subprocess-based video reader.
///
/// Uses FFmpeg to extract individual frames. This is slower than VapourSynth
/// but provides a reliable fallback when VS is not available.
pub struct FfmpegReader {
    path: PathBuf,
    fps: f64,
    frame_count: u32,
    width: u32,
    height: u32,
    #[allow(dead_code)]
    duration_ms: f64,
}

impl FfmpegReader {
    /// Open a video file with FFmpeg.
    ///
    /// # Arguments
    /// * `path` - Path to video file
    /// * `_config` - Reader configuration (currently unused for FFmpeg)
    ///
    /// # Returns
    /// FfmpegReader instance
    pub fn open(path: &Path, _config: &VideoReaderConfig) -> Result<Self, FrameError> {
        if !path.exists() {
            return Err(FrameError::OpenFailed {
                path: path.to_path_buf(),
                message: "File does not exist".to_string(),
            });
        }

        // Use ffprobe to get video properties
        let props = detect_properties(path)?;

        tracing::debug!(
            "[FFmpeg] Opened video: {}x{} @ {:.3} fps, {} frames",
            props.width,
            props.height,
            props.fps,
            props.frame_count
        );

        Ok(Self {
            path: path.to_path_buf(),
            fps: props.fps,
            frame_count: props.frame_count,
            width: props.width,
            height: props.height,
            duration_ms: props.duration_ms,
        })
    }

    /// Check if FFmpeg is available.
    pub fn is_available() -> bool {
        Command::new("ffmpeg")
            .arg("-version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }

    /// Extract a frame at a specific time using FFmpeg.
    fn extract_frame_at_time(&self, time_ms: f64) -> Result<DynamicImage, FrameError> {
        let time_secs = time_ms / 1000.0;

        // Format time as HH:MM:SS.mmm
        let hours = (time_secs / 3600.0) as u32;
        let minutes = ((time_secs % 3600.0) / 60.0) as u32;
        let seconds = time_secs % 60.0;
        let time_str = format!("{:02}:{:02}:{:06.3}", hours, minutes, seconds);

        tracing::trace!("[FFmpeg] Extracting frame at {}", time_str);

        // Use FFmpeg to extract a single frame as PNG to stdout
        let output = Command::new("ffmpeg")
            .args([
                "-ss",
                &time_str,
                "-i",
                self.path.to_str().unwrap_or(""),
                "-vframes",
                "1",
                "-f",
                "image2pipe",
                "-vcodec",
                "png",
                "-",
            ])
            .output()
            .map_err(|e| FrameError::ExtractionFailed {
                time_ms,
                message: format!("FFmpeg execution failed: {}", e),
            })?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(FrameError::ExtractionFailed {
                time_ms,
                message: format!("FFmpeg failed: {}", stderr.lines().last().unwrap_or("unknown error")),
            });
        }

        if output.stdout.is_empty() {
            return Err(FrameError::ExtractionFailed {
                time_ms,
                message: "FFmpeg produced no output".to_string(),
            });
        }

        // Decode PNG data
        let cursor = Cursor::new(output.stdout);
        let img = image::load(cursor, image::ImageFormat::Png).map_err(|e| {
            FrameError::ExtractionFailed {
                time_ms,
                message: format!("Failed to decode PNG: {}", e),
            }
        })?;

        Ok(img)
    }
}

impl VideoReader for FfmpegReader {
    fn get_frame(&self, index: u32) -> Result<DynamicImage, FrameError> {
        // Convert frame index to time
        let time_ms = index as f64 * 1000.0 / self.fps;
        self.extract_frame_at_time(time_ms)
    }

    fn get_frame_at_time(&self, time_ms: f64) -> Result<DynamicImage, FrameError> {
        self.extract_frame_at_time(time_ms)
    }

    fn get_pts(&self, index: u32) -> Result<f64, FrameError> {
        // FFmpeg doesn't easily give us PTS, so we estimate
        // This is less accurate than VapourSynth for VFR content
        Ok(index as f64 * 1000.0 / self.fps)
    }

    fn frame_count(&self) -> u32 {
        self.frame_count
    }

    fn fps(&self) -> f64 {
        self.fps
    }

    fn width(&self) -> u32 {
        self.width
    }

    fn height(&self) -> u32 {
        self.height
    }

    fn backend_name(&self) -> &str {
        "ffmpeg"
    }

    fn supports_deinterlace(&self) -> bool {
        // FFmpeg can deinterlace but we haven't implemented it in extract yet
        false
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_available() {
        // Just verify it doesn't panic
        let _available = FfmpegReader::is_available();
    }

    #[test]
    fn test_open_nonexistent() {
        let path = Path::new("/nonexistent/video.mkv");
        let config = VideoReaderConfig::default();
        let result = FfmpegReader::open(path, &config);
        assert!(result.is_err());
    }
}
