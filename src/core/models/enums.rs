//! Type enumerations

use serde::{Deserialize, Serialize};
use std::fmt;

/// Track type enumeration
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TrackType {
    Video,
    Audio,
    Subtitles,
}

impl fmt::Display for TrackType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            TrackType::Video => write!(f, "video"),
            TrackType::Audio => write!(f, "audio"),
            TrackType::Subtitles => write!(f, "subtitles"),
        }
    }
}

impl TrackType {
    /// Parse from mkvmerge JSON type string
    pub fn from_mkvmerge_type(s: &str) -> Option<Self> {
        match s {
            "video" => Some(TrackType::Video),
            "audio" => Some(TrackType::Audio),
            "subtitles" => Some(TrackType::Subtitles),
            _ => None,
        }
    }

    /// Convert to short prefix for UI display
    pub fn prefix(&self) -> &'static str {
        match self {
            TrackType::Video => "V",
            TrackType::Audio => "A",
            TrackType::Subtitles => "S",
        }
    }
}

/// Analysis mode enumeration
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum AnalysisMode {
    AudioCorrelation,
    VideoDiff,
}

impl fmt::Display for AnalysisMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            AnalysisMode::AudioCorrelation => write!(f, "Audio Correlation"),
            AnalysisMode::VideoDiff => write!(f, "VideoDiff"),
        }
    }
}

/// Merge mode enumeration
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum MergeMode {
    /// Profile-driven merge plan (rule-based)
    Plan,
    /// Manual track selection
    Manual,
}

impl fmt::Display for MergeMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            MergeMode::Plan => write!(f, "plan"),
            MergeMode::Manual => write!(f, "manual"),
        }
    }
}

/// Chapter snap mode
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum ChapterSnapMode {
    /// Snap to previous keyframe
    Previous,
    /// Snap to nearest keyframe
    Nearest,
}

impl fmt::Display for ChapterSnapMode {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            ChapterSnapMode::Previous => write!(f, "previous"),
            ChapterSnapMode::Nearest => write!(f, "nearest"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_track_type_parsing() {
        assert_eq!(
            TrackType::from_mkvmerge_type("video"),
            Some(TrackType::Video)
        );
        assert_eq!(
            TrackType::from_mkvmerge_type("audio"),
            Some(TrackType::Audio)
        );
        assert_eq!(
            TrackType::from_mkvmerge_type("subtitles"),
            Some(TrackType::Subtitles)
        );
        assert_eq!(TrackType::from_mkvmerge_type("unknown"), None);
    }

    #[test]
    fn test_track_type_prefix() {
        assert_eq!(TrackType::Video.prefix(), "V");
        assert_eq!(TrackType::Audio.prefix(), "A");
        assert_eq!(TrackType::Subtitles.prefix(), "S");
    }
}
