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

/// Audio filtering method for correlation analysis.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
pub enum FilteringMethod {
    /// No filtering applied.
    #[default]
    None,
    /// Low-pass filter.
    LowPass,
    /// Band-pass filter.
    BandPass,
    /// High-pass filter.
    HighPass,
}

impl std::fmt::Display for FilteringMethod {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            FilteringMethod::None => write!(f, "None"),
            FilteringMethod::LowPass => write!(f, "Low Pass"),
            FilteringMethod::BandPass => write!(f, "Band Pass"),
            FilteringMethod::HighPass => write!(f, "High Pass"),
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
    /// Snap to next keyframe.
    Next,
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

/// Sync mode controls how negative delays are handled.
///
/// When multiple sources are merged, some may need negative delays
/// (meaning they need to start before the reference). This affects
/// mkvmerge compatibility.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
pub enum SyncMode {
    /// Apply global shift to eliminate negative delays.
    /// All tracks shifted so none have negative delay.
    /// Required when secondary audio tracks are being merged.
    #[default]
    #[serde(rename = "positive_only")]
    PositiveOnly,
    /// Allow negative delays (no global shift).
    /// Use when you know your player/workflow handles negatives.
    #[serde(rename = "allow_negative")]
    AllowNegative,
}

impl SyncMode {
    /// Get the display name for this mode.
    pub fn name(&self) -> &'static str {
        match self {
            Self::PositiveOnly => "Positive Only (shift negatives)",
            Self::AllowNegative => "Allow Negative Delays",
        }
    }

    /// Get all available modes.
    pub fn all() -> &'static [SyncMode] {
        &[Self::PositiveOnly, Self::AllowNegative]
    }

    /// Create from index (for UI combo boxes).
    pub fn from_index(index: usize) -> Self {
        Self::all().get(index).copied().unwrap_or_default()
    }

    /// Get index of this mode (for UI combo boxes).
    pub fn to_index(&self) -> usize {
        Self::all().iter().position(|m| m == self).unwrap_or(0)
    }
}

impl std::fmt::Display for SyncMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.name())
    }
}

/// Audio correlation algorithm.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
pub enum CorrelationMethod {
    /// Standard Cross-Correlation (SCC).
    #[default]
    #[serde(rename = "Standard Correlation (SCC)")]
    Scc,
    /// Generalized Cross-Correlation with Phase Transform.
    #[serde(rename = "Phase Correlation (GCC-PHAT)")]
    GccPhat,
    /// GCC with Smoothed Coherence Transform.
    #[serde(rename = "GCC-SCOT")]
    GccScot,
    /// Whitened Cross-Correlation (robust to spectral differences).
    #[serde(rename = "Whitened Cross-Correlation")]
    Whitened,
    /// Onset Detection - correlates audio transients/attacks.
    #[serde(rename = "Onset Detection")]
    Onset,
    /// Dynamic Time Warping on MFCC features - handles tempo variations.
    #[serde(rename = "DTW (Dynamic Time Warping)")]
    Dtw,
    /// Spectrogram Correlation - mel-spectrogram based matching.
    #[serde(rename = "Spectrogram Correlation")]
    Spectrogram,
}

impl CorrelationMethod {
    /// Get the display name for this method.
    pub fn name(&self) -> &'static str {
        match self {
            Self::Scc => "Standard Correlation (SCC)",
            Self::GccPhat => "Phase Correlation (GCC-PHAT)",
            Self::GccScot => "GCC-SCOT",
            Self::Whitened => "Whitened Cross-Correlation",
            Self::Onset => "Onset Detection",
            Self::Dtw => "DTW (Dynamic Time Warping)",
            Self::Spectrogram => "Spectrogram Correlation",
        }
    }

    /// Get all available methods as a list.
    pub fn all() -> &'static [CorrelationMethod] {
        &[
            Self::Scc,
            Self::GccPhat,
            Self::GccScot,
            Self::Whitened,
            Self::Onset,
            Self::Dtw,
            Self::Spectrogram,
        ]
    }

    /// Create from index (for UI combo boxes).
    pub fn from_index(index: usize) -> Self {
        Self::all().get(index).copied().unwrap_or_default()
    }

    /// Get index of this method (for UI combo boxes).
    pub fn to_index(&self) -> usize {
        Self::all().iter().position(|m| m == self).unwrap_or(0)
    }
}

impl std::fmt::Display for CorrelationMethod {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.name())
    }
}

/// Method for selecting final delay from multiple chunk measurements.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
pub enum DelaySelectionMode {
    /// Most common rounded delay value.
    #[default]
    #[serde(rename = "Mode (Most Common)")]
    Mode,
    /// Mode with ±1ms clustering to handle vote-splitting.
    #[serde(rename = "Mode (Clustered)")]
    ModeClustered,
    /// Mode prioritizing clusters that appear early in the file.
    #[serde(rename = "Mode (Early Cluster)")]
    ModeEarly,
    /// First stable segment's delay (for stepping detection).
    #[serde(rename = "First Stable")]
    FirstStable,
    /// Average of all raw delay values.
    #[serde(rename = "Average")]
    Average,
}

impl DelaySelectionMode {
    /// Get the display name for this mode.
    pub fn name(&self) -> &'static str {
        match self {
            Self::Mode => "Mode (Most Common)",
            Self::ModeClustered => "Mode (Clustered)",
            Self::ModeEarly => "Mode (Early Cluster)",
            Self::FirstStable => "First Stable",
            Self::Average => "Average",
        }
    }

    /// Get all available modes as a list.
    pub fn all() -> &'static [DelaySelectionMode] {
        &[
            Self::Mode,
            Self::ModeClustered,
            Self::ModeEarly,
            Self::FirstStable,
            Self::Average,
        ]
    }

    /// Create from index (for UI combo boxes).
    pub fn from_index(index: usize) -> Self {
        Self::all().get(index).copied().unwrap_or_default()
    }

    /// Get index of this mode (for UI combo boxes).
    pub fn to_index(&self) -> usize {
        Self::all().iter().position(|m| m == self).unwrap_or(0)
    }
}

impl std::fmt::Display for DelaySelectionMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.name())
    }
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
