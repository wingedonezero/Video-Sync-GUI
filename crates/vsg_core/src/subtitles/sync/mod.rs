//! Subtitle sync modes.
//!
//! Pluggable sync strategies for adjusting subtitle timing.
//!
//! # Architecture
//!
//! Sync modes implement the `SyncMode` trait and are created via the factory function.
//! This follows the same pattern as `analysis::methods`.
//!
//! # Available Modes
//!
//! - **TimeBased**: Simple delay application - shifts all events by a constant offset.
//! - **VideoVerified**: Frame-matched delay - verifies audio correlation against video frames.

mod time_based;
mod video_verified;

pub use time_based::TimeBased;
pub use video_verified::VideoVerified;

use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::subtitles::error::SyncError;
use crate::subtitles::frame_utils::types::{
    ComparisonMethod, DeinterlaceMethod, HashAlgorithm, IndexerBackend, InterlacedForceMode,
};
use crate::subtitles::types::SubtitleData;

/// Available sync mode types.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
#[serde(rename_all = "kebab-case")]
pub enum SyncModeType {
    /// Simple delay application.
    #[default]
    TimeBased,
    /// Frame-matched delay verification.
    VideoVerified,
}

impl SyncModeType {
    /// Get the display name for this mode.
    pub fn name(&self) -> &'static str {
        match self {
            Self::TimeBased => "time-based",
            Self::VideoVerified => "video-verified",
        }
    }

    /// Get a description of this mode.
    pub fn description(&self) -> &'static str {
        match self {
            Self::TimeBased => "Apply delay offset to all subtitle events",
            Self::VideoVerified => "Verify delay against video frame matching",
        }
    }
}

/// Configuration for sync operations.
#[derive(Debug, Clone)]
pub struct SyncConfig {
    /// Total delay to apply (including global shift).
    pub total_delay_ms: f64,
    /// Global shift component of the delay.
    pub global_shift_ms: f64,
    /// Source video path (for video-verified mode).
    pub source_video: Option<std::path::PathBuf>,
    /// Target video path (for video-verified mode).
    pub target_video: Option<std::path::PathBuf>,
    /// Target video FPS (for frame calculations).
    pub target_fps: Option<f64>,
    /// Video-verified specific settings.
    pub video_verified: VideoVerifiedConfig,
}

impl Default for SyncConfig {
    fn default() -> Self {
        Self {
            total_delay_ms: 0.0,
            global_shift_ms: 0.0,
            source_video: None,
            target_video: None,
            target_fps: None,
            video_verified: VideoVerifiedConfig::default(),
        }
    }
}

impl SyncConfig {
    /// Create config for time-based sync.
    pub fn time_based(total_delay_ms: f64, global_shift_ms: f64) -> Self {
        Self {
            total_delay_ms,
            global_shift_ms,
            ..Default::default()
        }
    }

    /// Create config for video-verified sync.
    pub fn video_verified(
        total_delay_ms: f64,
        global_shift_ms: f64,
        source_video: impl AsRef<Path>,
        target_video: impl AsRef<Path>,
    ) -> Self {
        Self {
            total_delay_ms,
            global_shift_ms,
            source_video: Some(source_video.as_ref().to_path_buf()),
            target_video: Some(target_video.as_ref().to_path_buf()),
            ..Default::default()
        }
    }

    /// Pure correlation component (total - global shift).
    pub fn pure_correlation_ms(&self) -> f64 {
        self.total_delay_ms - self.global_shift_ms
    }
}

/// Video-verified mode specific settings.
#[derive(Debug, Clone)]
pub struct VideoVerifiedConfig {
    // General settings
    /// Number of checkpoints to test across the video.
    pub num_checkpoints: usize,
    /// Search range in frames around correlation value.
    pub search_range_frames: i32,
    /// Number of consecutive frames to verify.
    pub sequence_length: usize,
    /// Whether to use PTS precision for sub-frame accuracy.
    pub use_pts_precision: bool,
    /// Whether to run frame alignment audit.
    pub frame_audit_enabled: bool,

    // Hash settings
    /// Hash algorithm to use.
    pub hash_algorithm: HashAlgorithm,
    /// Hash size (8 or 16).
    pub hash_size: u8,
    /// Hash distance threshold for match.
    pub hash_threshold: u32,
    /// Window radius for initial frame search.
    pub window_radius: i32,
    /// Comparison method.
    pub comparison_method: ComparisonMethod,

    // Interlaced handling
    /// Whether interlaced handling is enabled.
    pub interlaced_handling_enabled: bool,
    /// Force mode for interlaced detection.
    pub interlaced_force_mode: InterlacedForceMode,
    /// Deinterlace method for interlaced content.
    pub interlaced_deinterlace_method: DeinterlaceMethod,
    /// Number of checkpoints for interlaced content.
    pub interlaced_num_checkpoints: usize,
    /// Search range for interlaced content.
    pub interlaced_search_range_frames: i32,
    /// Hash algorithm for interlaced content.
    pub interlaced_hash_algorithm: HashAlgorithm,
    /// Hash size for interlaced content.
    pub interlaced_hash_size: u8,
    /// Hash threshold for interlaced content.
    pub interlaced_hash_threshold: u32,
    /// Comparison method for interlaced content.
    pub interlaced_comparison_method: ComparisonMethod,
    /// Sequence length for interlaced content.
    pub interlaced_sequence_length: usize,
    /// Whether to fall back to audio if frame matching fails.
    pub interlaced_fallback_to_audio: bool,

    // Reader settings
    /// Indexer backend to use (FFMS2, BestSource, L-SMASH).
    pub indexer_backend: IndexerBackend,
}

impl Default for VideoVerifiedConfig {
    fn default() -> Self {
        Self {
            // General settings
            num_checkpoints: 5,
            search_range_frames: 3,
            sequence_length: 10,
            use_pts_precision: false,
            frame_audit_enabled: false,

            // Hash settings
            hash_algorithm: HashAlgorithm::PHash,
            hash_size: 16,
            hash_threshold: 12,
            window_radius: 1,
            comparison_method: ComparisonMethod::Hash,

            // Interlaced handling - same defaults, can be customized
            interlaced_handling_enabled: true,
            interlaced_force_mode: InterlacedForceMode::Auto,
            interlaced_deinterlace_method: DeinterlaceMethod::Bwdif,
            interlaced_num_checkpoints: 5,
            interlaced_search_range_frames: 3,
            interlaced_hash_algorithm: HashAlgorithm::PHash,
            interlaced_hash_size: 16,
            interlaced_hash_threshold: 15, // Slightly higher for interlaced
            interlaced_comparison_method: ComparisonMethod::Hash,
            interlaced_sequence_length: 10,
            interlaced_fallback_to_audio: true,

            // Reader settings
            indexer_backend: IndexerBackend::Ffms2,
        }
    }
}

impl VideoVerifiedConfig {
    /// Get the effective settings based on whether content is interlaced.
    pub fn effective_num_checkpoints(&self, is_interlaced: bool) -> usize {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_num_checkpoints
        } else {
            self.num_checkpoints
        }
    }

    /// Get effective search range.
    pub fn effective_search_range(&self, is_interlaced: bool) -> i32 {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_search_range_frames
        } else {
            self.search_range_frames
        }
    }

    /// Get effective hash algorithm.
    pub fn effective_hash_algorithm(&self, is_interlaced: bool) -> HashAlgorithm {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_hash_algorithm
        } else {
            self.hash_algorithm
        }
    }

    /// Get effective hash size.
    pub fn effective_hash_size(&self, is_interlaced: bool) -> u8 {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_hash_size
        } else {
            self.hash_size
        }
    }

    /// Get effective hash threshold.
    pub fn effective_hash_threshold(&self, is_interlaced: bool) -> u32 {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_hash_threshold
        } else {
            self.hash_threshold
        }
    }

    /// Get effective comparison method.
    pub fn effective_comparison_method(&self, is_interlaced: bool) -> ComparisonMethod {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_comparison_method
        } else {
            self.comparison_method
        }
    }

    /// Get effective sequence length.
    pub fn effective_sequence_length(&self, is_interlaced: bool) -> usize {
        if is_interlaced && self.interlaced_handling_enabled {
            self.interlaced_sequence_length
        } else {
            self.sequence_length
        }
    }
}

/// Result of a sync operation.
#[derive(Debug, Clone)]
pub struct SyncResult {
    /// Number of events affected.
    pub events_affected: usize,
    /// Final offset applied (may differ from config if video-verified).
    pub final_offset_ms: f64,
    /// Summary message.
    pub summary: String,
    /// Additional details.
    pub details: SyncDetails,
}

/// Additional sync result details.
#[derive(Debug, Clone, Default)]
pub struct SyncDetails {
    /// Reason for the offset selection.
    pub reason: String,
    /// Audio correlation value (before video verification).
    pub audio_correlation_ms: Option<f64>,
    /// Video-verified offset (if different from audio).
    pub video_offset_ms: Option<f64>,
    /// Whether frame matching was successful.
    pub frame_match_success: Option<bool>,
    /// Number of checkpoints matched.
    pub checkpoints_matched: Option<usize>,
}

/// Trait for sync mode implementations.
///
/// Each sync mode takes subtitle data and a config, and returns a result.
/// The sync mode may modify the subtitle data in place.
pub trait SyncMode: Send + Sync {
    /// Get the name of this sync mode.
    fn name(&self) -> &str;

    /// Get a description of this sync mode.
    fn description(&self) -> &str;

    /// Apply sync to subtitle data.
    ///
    /// # Arguments
    /// * `data` - Subtitle data to modify in place.
    /// * `config` - Sync configuration.
    ///
    /// # Returns
    /// * `Ok(SyncResult)` - Sync applied successfully.
    /// * `Err(SyncError)` - Sync failed.
    fn apply(&self, data: &mut SubtitleData, config: &SyncConfig) -> Result<SyncResult, SyncError>;
}

/// Create a sync mode from type enum.
pub fn create_sync_mode(mode: SyncModeType) -> Box<dyn SyncMode> {
    match mode {
        SyncModeType::TimeBased => Box::new(TimeBased),
        SyncModeType::VideoVerified => Box::new(VideoVerified),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_sync_mode_type_names() {
        assert_eq!(SyncModeType::TimeBased.name(), "time-based");
        assert_eq!(SyncModeType::VideoVerified.name(), "video-verified");
    }

    #[test]
    fn test_sync_config_pure_correlation() {
        let config = SyncConfig {
            total_delay_ms: 150.0,
            global_shift_ms: 50.0,
            ..Default::default()
        };
        assert!((config.pure_correlation_ms() - 100.0).abs() < 0.001);
    }
}
