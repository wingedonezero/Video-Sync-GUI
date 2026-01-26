//! Extraction types and error definitions.
//!
//! Provides types for track extraction, file probing, and
//! errors that can occur during extraction operations.

use std::path::PathBuf;

use serde::{Deserialize, Serialize};

/// Track type enumeration.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TrackType {
    Video,
    Audio,
    Subtitles,
}

impl TrackType {
    /// Get the type prefix for display (V, A, S).
    pub fn prefix(&self) -> &'static str {
        match self {
            TrackType::Video => "V",
            TrackType::Audio => "A",
            TrackType::Subtitles => "S",
        }
    }

    /// Parse from string.
    pub fn from_str(s: &str) -> Option<Self> {
        match s.to_lowercase().as_str() {
            "video" => Some(TrackType::Video),
            "audio" => Some(TrackType::Audio),
            "subtitles" => Some(TrackType::Subtitles),
            _ => None,
        }
    }
}

impl std::fmt::Display for TrackType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            TrackType::Video => write!(f, "video"),
            TrackType::Audio => write!(f, "audio"),
            TrackType::Subtitles => write!(f, "subtitles"),
        }
    }
}

/// Information about a track in a container.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TrackInfo {
    /// Track ID (as used by mkvextract).
    pub id: usize,
    /// Track type.
    pub track_type: TrackType,
    /// Codec identifier (e.g., "A_AAC", "V_MPEG4/ISO/AVC").
    pub codec_id: String,
    /// Human-readable codec name (e.g., "AAC", "AVC/H.264").
    pub codec_name: String,
    /// Language code (ISO 639-2, e.g., "eng", "jpn", "und").
    pub language: Option<String>,
    /// Track name/title.
    pub name: Option<String>,
    /// Whether this is the default track.
    pub is_default: bool,
    /// Whether this is a forced track.
    pub is_forced: bool,
    /// Whether this track is enabled.
    pub is_enabled: bool,
    /// Track-specific properties.
    pub properties: TrackProperties,
}

/// Track-specific properties based on track type.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct TrackProperties {
    // Video properties
    /// Video width in pixels.
    pub width: Option<u32>,
    /// Video height in pixels.
    pub height: Option<u32>,
    /// Display dimensions (may differ from encoded).
    pub display_dimensions: Option<String>,
    /// Frame rate (calculated from default_duration).
    pub fps: Option<f64>,

    // Audio properties
    /// Number of audio channels.
    pub channels: Option<u8>,
    /// Sample rate in Hz.
    pub sample_rate: Option<u32>,
    /// Bits per sample.
    pub bits_per_sample: Option<u8>,

    // Subtitle properties
    /// Whether subtitles are text-based or image-based.
    pub text_subtitles: Option<bool>,
}

impl TrackInfo {
    /// Get a formatted summary string for display.
    pub fn summary(&self) -> String {
        let type_prefix = self.track_type.prefix();
        let lang = self.language.as_deref().unwrap_or("und");

        match self.track_type {
            TrackType::Video => {
                let dims = self
                    .properties
                    .display_dimensions
                    .clone()
                    .or_else(|| {
                        self.properties
                            .width
                            .zip(self.properties.height)
                            .map(|(w, h)| format!("{}x{}", w, h))
                    })
                    .unwrap_or_default();

                let fps_str = self
                    .properties
                    .fps
                    .map(|f| format!(", {:.3} fps", f))
                    .unwrap_or_default();

                format!(
                    "[{}-{}] {} ({}) | {}{}",
                    type_prefix, self.id, self.codec_name, lang, dims, fps_str
                )
            }
            TrackType::Audio => {
                let channels = self.properties.channels.unwrap_or(2);
                let sample_rate = self.properties.sample_rate.unwrap_or(48000);
                let ch_str = channel_layout_string(channels);

                format!(
                    "[{}-{}] {} ({}) | {} Hz, {}",
                    type_prefix, self.id, self.codec_name, lang, sample_rate, ch_str
                )
            }
            TrackType::Subtitles => {
                format!("[{}-{}] {} ({})", type_prefix, self.id, self.codec_name, lang)
            }
        }
    }

    /// Get badge strings (Default, Forced, etc.).
    pub fn badges(&self) -> Vec<&'static str> {
        let mut badges = Vec::new();
        if self.is_default {
            badges.push("Default");
        }
        if self.is_forced {
            badges.push("Forced");
        }
        badges
    }
}

/// Convert channel count to a human-readable string.
fn channel_layout_string(channels: u8) -> String {
    match channels {
        1 => "Mono".to_string(),
        2 => "Stereo".to_string(),
        6 => "5.1".to_string(),
        8 => "7.1".to_string(),
        _ => format!("{} ch", channels),
    }
}

/// Information about an attachment in a container.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AttachmentInfo {
    /// Attachment ID.
    pub id: usize,
    /// Filename.
    pub name: String,
    /// MIME type.
    pub mime_type: String,
    /// Size in bytes.
    pub size: u64,
    /// Description (optional).
    pub description: Option<String>,
}

impl AttachmentInfo {
    /// Check if this is a font file (commonly embedded in MKV for subtitles).
    pub fn is_font(&self) -> bool {
        let mime_lower = self.mime_type.to_lowercase();
        let name_lower = self.name.to_lowercase();

        mime_lower.contains("font")
            || mime_lower == "application/x-truetype-font"
            || mime_lower == "application/vnd.ms-opentype"
            || name_lower.ends_with(".ttf")
            || name_lower.ends_with(".otf")
            || name_lower.ends_with(".ttc")
            || name_lower.ends_with(".woff")
            || name_lower.ends_with(".woff2")
    }
}

/// Complete probe result for a container file.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ProbeResult {
    /// Container format.
    pub container: String,
    /// Container duration in nanoseconds.
    pub duration_ns: Option<u64>,
    /// List of tracks.
    pub tracks: Vec<TrackInfo>,
    /// List of attachments.
    pub attachments: Vec<AttachmentInfo>,
    /// Whether the file has chapters.
    pub has_chapters: bool,
    /// File path that was probed.
    pub file_path: PathBuf,
}

impl ProbeResult {
    /// Get all video tracks.
    pub fn video_tracks(&self) -> impl Iterator<Item = &TrackInfo> {
        self.tracks
            .iter()
            .filter(|t| t.track_type == TrackType::Video)
    }

    /// Get all audio tracks.
    pub fn audio_tracks(&self) -> impl Iterator<Item = &TrackInfo> {
        self.tracks
            .iter()
            .filter(|t| t.track_type == TrackType::Audio)
    }

    /// Get all subtitle tracks.
    pub fn subtitle_tracks(&self) -> impl Iterator<Item = &TrackInfo> {
        self.tracks
            .iter()
            .filter(|t| t.track_type == TrackType::Subtitles)
    }

    /// Find a track by ID.
    pub fn track_by_id(&self, id: usize) -> Option<&TrackInfo> {
        self.tracks.iter().find(|t| t.id == id)
    }

    /// Find tracks by language.
    pub fn tracks_by_language(&self, lang: &str) -> Vec<&TrackInfo> {
        self.tracks
            .iter()
            .filter(|t| t.language.as_deref() == Some(lang))
            .collect()
    }

    /// Get the first default video track.
    pub fn default_video(&self) -> Option<&TrackInfo> {
        self.video_tracks().find(|t| t.is_default).or_else(|| self.video_tracks().next())
    }

    /// Get the first default audio track.
    pub fn default_audio(&self) -> Option<&TrackInfo> {
        self.audio_tracks().find(|t| t.is_default).or_else(|| self.audio_tracks().next())
    }

    /// Get duration in seconds.
    pub fn duration_secs(&self) -> Option<f64> {
        self.duration_ns.map(|ns| ns as f64 / 1_000_000_000.0)
    }
}

/// Result of extracting a track.
#[derive(Debug, Clone)]
pub struct ExtractedTrack {
    /// Track ID that was extracted.
    pub track_id: usize,
    /// Track type.
    pub track_type: TrackType,
    /// Path to the extracted file.
    pub output_path: PathBuf,
}

/// Result of extracting attachments.
#[derive(Debug, Clone)]
pub struct ExtractedAttachments {
    /// Directory containing extracted attachments.
    pub output_dir: PathBuf,
    /// List of extracted attachment files.
    pub files: Vec<PathBuf>,
}

/// Error types for extraction operations.
#[derive(Debug, thiserror::Error)]
pub enum ExtractionError {
    /// File not found.
    #[error("File not found: {0}")]
    FileNotFound(PathBuf),

    /// Invalid container format.
    #[error("Invalid or unsupported container: {0}")]
    InvalidContainer(String),

    /// Track not found.
    #[error("Track {0} not found in container")]
    TrackNotFound(usize),

    /// Probe failed.
    #[error("Failed to probe file: {0}")]
    ProbeFailed(String),

    /// Extraction failed.
    #[error("Extraction failed: {0}")]
    ExtractionFailed(String),

    /// Command execution failed.
    #[error("{tool} failed with exit code {exit_code}: {message}")]
    CommandFailed {
        tool: String,
        exit_code: i32,
        message: String,
    },

    /// IO error.
    #[error("IO error: {0}")]
    IoError(#[from] std::io::Error),

    /// JSON parsing error.
    #[error("JSON parse error: {0}")]
    JsonError(#[from] serde_json::Error),
}

/// Type alias for extraction operation results.
pub type ExtractionResult<T> = Result<T, ExtractionError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn track_type_display() {
        assert_eq!(TrackType::Video.to_string(), "video");
        assert_eq!(TrackType::Audio.to_string(), "audio");
        assert_eq!(TrackType::Subtitles.to_string(), "subtitles");
    }

    #[test]
    fn track_type_prefix() {
        assert_eq!(TrackType::Video.prefix(), "V");
        assert_eq!(TrackType::Audio.prefix(), "A");
        assert_eq!(TrackType::Subtitles.prefix(), "S");
    }

    #[test]
    fn channel_layout() {
        assert_eq!(channel_layout_string(1), "Mono");
        assert_eq!(channel_layout_string(2), "Stereo");
        assert_eq!(channel_layout_string(6), "5.1");
        assert_eq!(channel_layout_string(8), "7.1");
        assert_eq!(channel_layout_string(4), "4 ch");
    }

    #[test]
    fn attachment_is_font() {
        let font = AttachmentInfo {
            id: 1,
            name: "Arial.ttf".to_string(),
            mime_type: "application/x-truetype-font".to_string(),
            size: 1024,
            description: None,
        };
        assert!(font.is_font());

        let cover = AttachmentInfo {
            id: 2,
            name: "cover.jpg".to_string(),
            mime_type: "image/jpeg".to_string(),
            size: 2048,
            description: None,
        };
        assert!(!cover.is_font());
    }
}
