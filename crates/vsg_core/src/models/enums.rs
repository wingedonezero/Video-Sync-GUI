//! Core enums used throughout the application.

use serde::{Deserialize, Serialize};

/// Type of media track.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum TrackType {
    Video,
    Audio,
    Subtitles,
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

/// Analysis method for calculating sync delays.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
pub enum AnalysisMode {
    /// Cross-correlation of audio waveforms.
    #[default]
    #[serde(rename = "Audio Correlation")]
    AudioCorrelation,
    /// Video frame difference analysis.
    #[serde(rename = "VideoDiff")]
    VideoDiff,
}

impl std::fmt::Display for AnalysisMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AnalysisMode::AudioCorrelation => write!(f, "Audio Correlation"),
            AnalysisMode::VideoDiff => write!(f, "VideoDiff"),
        }
    }
}

/// Mode for snapping chapters to keyframes.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SnapMode {
    /// Snap to previous keyframe.
    #[default]
    Previous,
    /// Snap to nearest keyframe.
    Nearest,
}

/// Status of a completed job.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum JobStatus {
    /// Successfully merged output file.
    Merged,
    /// Analysis completed (no merge).
    Analyzed,
    /// Job failed with error.
    Failed,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn track_type_serializes_lowercase() {
        let json = serde_json::to_string(&TrackType::Audio).unwrap();
        assert_eq!(json, "\"audio\"");
    }

    #[test]
    fn track_type_deserializes_lowercase() {
        let track: TrackType = serde_json::from_str("\"subtitles\"").unwrap();
        assert_eq!(track, TrackType::Subtitles);
    }

    #[test]
    fn analysis_mode_serializes_display_name() {
        let json = serde_json::to_string(&AnalysisMode::AudioCorrelation).unwrap();
        assert_eq!(json, "\"Audio Correlation\"");
    }
}
