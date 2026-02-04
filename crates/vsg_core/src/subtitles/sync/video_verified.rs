//! Video-verified sync mode.
//!
//! Uses frame matching to verify the audio correlation offset against actual video frames.
//!
//! # Algorithm
//!
//! 1. Start with the audio correlation delay as a baseline
//! 2. Generate candidate frame offsets around the correlation value
//! 3. Test each candidate at multiple checkpoints across the video
//! 4. Select the best matching frame offset using sequence verification
//! 5. Apply the verified offset (which may differ from audio correlation)
//!
//! # Use Cases
//!
//! Use this mode when:
//! - Subtitles are timed to VIDEO, not audio
//! - Audio may have a slight offset from video in the source
//! - You need frame-accurate subtitle timing
//! - The audio correlation seems slightly off (e.g., 1 frame / ~42ms)
//!
//! # Requirements
//!
//! - Both source and target video paths must be provided
//! - FFmpeg must be available for frame extraction
//! - Target video FPS should be provided for accurate frame calculations

use crate::subtitles::error::SyncError;
use crate::subtitles::types::{SubtitleData, SyncEventData};

use super::{SyncConfig, SyncDetails, SyncMode, SyncResult};

/// Video-verified sync mode.
///
/// Verifies audio correlation against video frame matching.
pub struct VideoVerified;

impl SyncMode for VideoVerified {
    fn name(&self) -> &str {
        "video-verified"
    }

    fn description(&self) -> &str {
        "Verify delay against video frame matching"
    }

    fn apply(&self, data: &mut SubtitleData, config: &SyncConfig) -> Result<SyncResult, SyncError> {
        if data.events.is_empty() {
            return Err(SyncError::NoEvents);
        }

        // Validate required inputs
        let source_video = config.source_video.as_ref().ok_or_else(|| {
            SyncError::MissingVideo("source_video required for video-verified mode".to_string())
        })?;

        let target_video = config.target_video.as_ref().ok_or_else(|| {
            SyncError::MissingVideo("target_video required for video-verified mode".to_string())
        })?;

        // For now, fall back to time-based sync with a note
        // Full implementation requires frame_utils module
        //
        // TODO: Implement frame matching when frame_utils is ready:
        // 1. Open video readers for source and target
        // 2. Detect FPS if not provided
        // 3. Generate candidate frame offsets around correlation
        // 4. Test each candidate at checkpoints
        // 5. Select best using sequence verification
        // 6. Calculate final offset

        let pure_correlation_ms = config.pure_correlation_ms();
        let final_offset_ms = config.total_delay_ms;

        // Check if frame utils are available
        let frame_utils_available = false; // TODO: check for FFmpeg/frame utils

        let (reason, frame_match_success) = if !frame_utils_available {
            tracing::warn!(
                "Video-verified mode: frame utilities not available, falling back to time-based"
            );
            ("fallback-no-frame-utils".to_string(), None)
        } else if !source_video.exists() {
            tracing::warn!(
                "Video-verified mode: source video not found at {:?}",
                source_video
            );
            ("fallback-source-not-found".to_string(), None)
        } else if !target_video.exists() {
            tracing::warn!(
                "Video-verified mode: target video not found at {:?}",
                target_video
            );
            ("fallback-target-not-found".to_string(), None)
        } else {
            // Would do frame matching here
            ("fallback-not-implemented".to_string(), None)
        };

        // Apply offset to all events (same as time-based for now)
        let mut events_affected = 0;

        for event in &mut data.events {
            if event.is_comment {
                continue;
            }

            let original_start = event.start_ms;
            let original_end = event.end_ms;

            event.start_ms = (event.start_ms + final_offset_ms).max(0.0);
            event.end_ms = (event.end_ms + final_offset_ms).max(0.0);

            event.sync_data = Some(SyncEventData {
                original_start_ms: original_start,
                original_end_ms: original_end,
                start_adjustment_ms: final_offset_ms,
                end_adjustment_ms: final_offset_ms,
                snapped_to_frame: false,
                snapped_frame: None,
            });

            events_affected += 1;
        }

        let summary = format!(
            "VideoVerified: {} events, {:+.1}ms ({})",
            events_affected, final_offset_ms, reason
        );

        Ok(SyncResult {
            events_affected,
            final_offset_ms,
            summary,
            details: SyncDetails {
                reason,
                audio_correlation_ms: Some(pure_correlation_ms),
                video_offset_ms: Some(pure_correlation_ms), // Same until frame matching implemented
                frame_match_success,
                checkpoints_matched: None,
            },
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::subtitles::types::SubtitleEvent;
    use std::path::PathBuf;

    #[test]
    fn test_video_verified_missing_source() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 2000.0, "Test"));

        let config = SyncConfig {
            total_delay_ms: 100.0,
            global_shift_ms: 0.0,
            source_video: None,
            target_video: Some(PathBuf::from("/tmp/target.mkv")),
            ..Default::default()
        };

        let sync = VideoVerified;
        let result = sync.apply(&mut data, &config);

        assert!(matches!(result, Err(SyncError::MissingVideo(_))));
    }

    #[test]
    fn test_video_verified_missing_target() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 2000.0, "Test"));

        let config = SyncConfig {
            total_delay_ms: 100.0,
            global_shift_ms: 0.0,
            source_video: Some(PathBuf::from("/tmp/source.mkv")),
            target_video: None,
            ..Default::default()
        };

        let sync = VideoVerified;
        let result = sync.apply(&mut data, &config);

        assert!(matches!(result, Err(SyncError::MissingVideo(_))));
    }

    #[test]
    fn test_video_verified_fallback() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 2000.0, "Test"));

        let config = SyncConfig {
            total_delay_ms: 150.0,
            global_shift_ms: 50.0,
            source_video: Some(PathBuf::from("/nonexistent/source.mkv")),
            target_video: Some(PathBuf::from("/nonexistent/target.mkv")),
            ..Default::default()
        };

        let sync = VideoVerified;
        let result = sync.apply(&mut data, &config).unwrap();

        // Should fall back to time-based behavior
        assert_eq!(result.events_affected, 1);
        assert!((result.final_offset_ms - 150.0).abs() < 0.001);
        assert!(result.details.reason.starts_with("fallback"));
    }
}
