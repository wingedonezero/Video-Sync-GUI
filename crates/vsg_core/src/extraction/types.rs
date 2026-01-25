//! Types for extraction operations.
//!
//! These types represent the results of extracting tracks and reading
//! container information from media files.

use std::collections::HashMap;
use std::path::PathBuf;

use serde::{Deserialize, Serialize};

use crate::models::TrackType;

/// Error type for extraction operations.
#[derive(Debug, Clone)]
pub enum ExtractionError {
    /// File not found.
    FileNotFound(PathBuf),
    /// Failed to execute external tool.
    ToolExecutionFailed { tool: String, message: String },
    /// Failed to parse tool output.
    ParseError { tool: String, message: String },
    /// Track extraction failed.
    TrackExtractionFailed { track_id: usize, message: String },
    /// Attachment extraction failed.
    AttachmentExtractionFailed { attachment_id: usize, message: String },
    /// Output file missing or empty after extraction.
    OutputMissing(PathBuf),
    /// General I/O error.
    IoError(String),
}

impl std::fmt::Display for ExtractionError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ExtractionError::FileNotFound(path) => {
                write!(f, "File not found: {}", path.display())
            }
            ExtractionError::ToolExecutionFailed { tool, message } => {
                write!(f, "{} execution failed: {}", tool, message)
            }
            ExtractionError::ParseError { tool, message } => {
                write!(f, "Failed to parse {} output: {}", tool, message)
            }
            ExtractionError::TrackExtractionFailed { track_id, message } => {
                write!(f, "Failed to extract track {}: {}", track_id, message)
            }
            ExtractionError::AttachmentExtractionFailed { attachment_id, message } => {
                write!(f, "Failed to extract attachment {}: {}", attachment_id, message)
            }
            ExtractionError::OutputMissing(path) => {
                write!(f, "Output file missing or empty: {}", path.display())
            }
            ExtractionError::IoError(msg) => {
                write!(f, "I/O error: {}", msg)
            }
        }
    }
}

impl std::error::Error for ExtractionError {}

/// Container timing information for a source file.
///
/// This reads the `minimum_timestamp` property from mkvmerge -J output
/// which represents the container delay for each track.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContainerInfo {
    /// Source key ("Source 1", "Source 2", etc.)
    pub source_key: String,

    /// Path to the source file.
    pub source_path: PathBuf,

    /// Track ID -> container delay in milliseconds.
    /// Container delay = minimum_timestamp / 1,000,000 (ns to ms)
    pub track_delays_ms: HashMap<usize, i64>,

    /// Video track ID (first video track found).
    pub video_track_id: Option<usize>,

    /// Video track's container delay in milliseconds.
    /// Used as the reference timeline for Source 1.
    pub video_delay_ms: i64,

    /// Duration of the file in milliseconds.
    pub duration_ms: i64,
}

impl ContainerInfo {
    /// Create new container info.
    pub fn new(source_key: impl Into<String>, source_path: PathBuf) -> Self {
        Self {
            source_key: source_key.into(),
            source_path,
            track_delays_ms: HashMap::new(),
            video_track_id: None,
            video_delay_ms: 0,
            duration_ms: 0,
        }
    }

    /// Get the container delay for a specific track.
    pub fn track_delay(&self, track_id: usize) -> i64 {
        self.track_delays_ms.get(&track_id).copied().unwrap_or(0)
    }

    /// Get the relative delay for an audio track.
    ///
    /// This calculates `audio_delay - video_delay` which preserves
    /// the internal A/V sync of Source 1 when applied to the merge.
    ///
    /// # Why Relative Delay?
    ///
    /// Source 1's video track defines the output timeline. If Source 1
    /// has an audio track that starts slightly later than video (common
    /// in broadcast captures), we need to preserve that offset.
    ///
    /// Example:
    /// - Video container delay: 100ms
    /// - Audio container delay: 150ms
    /// - Relative audio delay: 150 - 100 = 50ms
    ///
    /// The audio will be delayed by 50ms relative to video, preserving sync.
    pub fn relative_audio_delay(&self, track_id: usize) -> i64 {
        let audio_delay = self.track_delay(track_id);
        audio_delay - self.video_delay_ms
    }
}

/// Information about an extracted track.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractedTrack {
    /// Source key this track came from.
    pub source_key: String,

    /// Track ID within the source file.
    pub track_id: usize,

    /// Type of track.
    pub track_type: TrackType,

    /// Codec ID (e.g., "A_FLAC", "S_TEXT/ASS").
    pub codec_id: String,

    /// Path to the extracted file.
    pub extracted_path: PathBuf,

    /// Original file extension.
    pub extension: String,
}

/// Request to extract a track from a source file.
#[derive(Debug, Clone)]
pub struct ExtractRequest {
    /// Source key for tracking.
    pub source_key: String,

    /// Path to the source file.
    pub source_path: PathBuf,

    /// Track ID to extract.
    pub track_id: usize,

    /// Track type for proper extension handling.
    pub track_type: TrackType,

    /// Codec ID for proper extension handling.
    pub codec_id: String,

    /// Output directory for extracted file.
    pub output_dir: PathBuf,
}

/// Information about an extracted attachment.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractedAttachment {
    /// Source key this attachment came from.
    pub source_key: String,

    /// Attachment ID within the source file.
    pub attachment_id: usize,

    /// Original filename.
    pub file_name: String,

    /// MIME type.
    pub mime_type: String,

    /// Path to the extracted file.
    pub extracted_path: PathBuf,
}

/// Complete extraction output for a job.
///
/// This is the output of the ExtractStep and contains all information
/// needed by subsequent steps (Chapters, Mux).
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ExtractionOutput {
    /// Container info for each source.
    /// Key: source key ("Source 1", "Source 2", etc.)
    pub container_info: HashMap<String, ContainerInfo>,

    /// Extracted tracks.
    /// Key: "{source_key}:{track_id}" (e.g., "Source 2:1")
    pub extracted_tracks: HashMap<String, ExtractedTrack>,

    /// Extracted attachments (fonts, etc.)
    pub attachments: Vec<ExtractedAttachment>,
}

impl ExtractionOutput {
    /// Create new empty extraction output.
    pub fn new() -> Self {
        Self::default()
    }

    /// Add container info for a source.
    pub fn add_container_info(&mut self, info: ContainerInfo) {
        self.container_info.insert(info.source_key.clone(), info);
    }

    /// Add an extracted track.
    pub fn add_track(&mut self, track: ExtractedTrack) {
        let key = format!("{}:{}", track.source_key, track.track_id);
        self.extracted_tracks.insert(key, track);
    }

    /// Get container info for a source.
    pub fn get_container_info(&self, source_key: &str) -> Option<&ContainerInfo> {
        self.container_info.get(source_key)
    }

    /// Get an extracted track by source key and track ID.
    pub fn get_track(&self, source_key: &str, track_id: usize) -> Option<&ExtractedTrack> {
        let key = format!("{}:{}", source_key, track_id);
        self.extracted_tracks.get(&key)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn container_info_relative_delay() {
        let mut info = ContainerInfo::new("Source 1", PathBuf::from("/test.mkv"));
        info.video_delay_ms = 100;
        info.track_delays_ms.insert(0, 100); // Video track
        info.track_delays_ms.insert(1, 150); // Audio track
        info.track_delays_ms.insert(2, 100); // Subtitle track

        // Audio is 50ms behind video
        assert_eq!(info.relative_audio_delay(1), 50);
        // Subtitle is in sync with video
        assert_eq!(info.relative_audio_delay(2), 0);
        // Missing track returns 0 relative to video
        assert_eq!(info.relative_audio_delay(99), -100);
    }

    #[test]
    fn extraction_output_track_lookup() {
        let mut output = ExtractionOutput::new();
        output.add_track(ExtractedTrack {
            source_key: "Source 2".to_string(),
            track_id: 1,
            track_type: TrackType::Audio,
            codec_id: "A_FLAC".to_string(),
            extracted_path: PathBuf::from("/temp/track_1.flac"),
            extension: "flac".to_string(),
        });

        assert!(output.get_track("Source 2", 1).is_some());
        assert!(output.get_track("Source 2", 2).is_none());
        assert!(output.get_track("Source 1", 1).is_none());
    }
}
