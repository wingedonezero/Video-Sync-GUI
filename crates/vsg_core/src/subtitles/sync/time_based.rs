//! Time-based sync mode.
//!
//! Simple delay application - shifts all subtitle events by a constant offset.
//!
//! This is the most straightforward sync mode:
//! - Takes the delay from audio correlation
//! - Applies it directly to all subtitle events
//! - No frame verification or additional calculations
//!
//! Use this mode when:
//! - Subtitles are timed to audio (most common case)
//! - You trust the audio correlation result
//! - Video frame matching is not needed or not possible

use crate::subtitles::error::SyncError;
use crate::subtitles::types::{SubtitleData, SyncEventData};

use super::{SyncConfig, SyncDetails, SyncMode, SyncResult};

/// Time-based sync mode.
///
/// Applies a constant delay offset to all subtitle events.
pub struct TimeBased;

impl SyncMode for TimeBased {
    fn name(&self) -> &str {
        "time-based"
    }

    fn description(&self) -> &str {
        "Apply delay offset to all subtitle events"
    }

    fn apply(&self, data: &mut SubtitleData, config: &SyncConfig) -> Result<SyncResult, SyncError> {
        if data.events.is_empty() {
            return Err(SyncError::NoEvents);
        }

        let offset_ms = config.total_delay_ms;
        let mut events_affected = 0;

        for event in &mut data.events {
            // Skip comments
            if event.is_comment {
                continue;
            }

            // Record original times
            let original_start = event.start_ms;
            let original_end = event.end_ms;

            // Apply offset (clamp to 0)
            event.start_ms = (event.start_ms + offset_ms).max(0.0);
            event.end_ms = (event.end_ms + offset_ms).max(0.0);

            // Record sync data for debugging/auditing
            event.sync_data = Some(SyncEventData {
                original_start_ms: original_start,
                original_end_ms: original_end,
                start_adjustment_ms: offset_ms,
                end_adjustment_ms: offset_ms,
                snapped_to_frame: false,
                snapped_frame: None,
            });

            events_affected += 1;
        }

        let summary = format!(
            "TimeBased: {} events shifted by {:+.1}ms",
            events_affected, offset_ms
        );

        Ok(SyncResult {
            events_affected,
            final_offset_ms: offset_ms,
            summary,
            details: SyncDetails {
                reason: "time-based-direct".to_string(),
                audio_correlation_ms: Some(config.pure_correlation_ms()),
                video_offset_ms: None,
                frame_match_success: None,
                checkpoints_matched: None,
            },
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::subtitles::types::SubtitleEvent;

    #[test]
    fn test_time_based_positive_offset() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 4000.0, "Test 1"));
        data.events
            .push(SubtitleEvent::new(5000.0, 8000.0, "Test 2"));

        let config = SyncConfig::time_based(500.0, 0.0);
        let sync = TimeBased;
        let result = sync.apply(&mut data, &config).unwrap();

        assert_eq!(result.events_affected, 2);
        assert!((result.final_offset_ms - 500.0).abs() < 0.001);

        // Check events were shifted
        assert!((data.events[0].start_ms - 1500.0).abs() < 0.001);
        assert!((data.events[0].end_ms - 4500.0).abs() < 0.001);
        assert!((data.events[1].start_ms - 5500.0).abs() < 0.001);
        assert!((data.events[1].end_ms - 8500.0).abs() < 0.001);

        // Check sync data was recorded
        let sync_data = data.events[0].sync_data.as_ref().unwrap();
        assert!((sync_data.original_start_ms - 1000.0).abs() < 0.001);
        assert!((sync_data.start_adjustment_ms - 500.0).abs() < 0.001);
    }

    #[test]
    fn test_time_based_negative_offset_clamped() {
        let mut data = SubtitleData::new();
        data.events.push(SubtitleEvent::new(500.0, 2000.0, "Test"));

        let config = SyncConfig::time_based(-1000.0, 0.0);
        let sync = TimeBased;
        let result = sync.apply(&mut data, &config).unwrap();

        assert_eq!(result.events_affected, 1);

        // Start should be clamped to 0
        assert!((data.events[0].start_ms - 0.0).abs() < 0.001);
        // End should be 2000 - 1000 = 1000
        assert!((data.events[0].end_ms - 1000.0).abs() < 0.001);
    }

    #[test]
    fn test_time_based_skips_comments() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 2000.0, "Dialogue"));

        let mut comment = SubtitleEvent::new(1500.0, 2500.0, "Comment");
        comment.is_comment = true;
        data.events.push(comment);

        let config = SyncConfig::time_based(500.0, 0.0);
        let sync = TimeBased;
        let result = sync.apply(&mut data, &config).unwrap();

        // Only dialogue should be affected
        assert_eq!(result.events_affected, 1);

        // Dialogue shifted
        assert!((data.events[0].start_ms - 1500.0).abs() < 0.001);

        // Comment unchanged
        assert!((data.events[1].start_ms - 1500.0).abs() < 0.001);
    }

    #[test]
    fn test_time_based_empty_data() {
        let mut data = SubtitleData::new();
        let config = SyncConfig::time_based(500.0, 0.0);
        let sync = TimeBased;

        let result = sync.apply(&mut data, &config);
        assert!(matches!(result, Err(SyncError::NoEvents)));
    }

    #[test]
    fn test_time_based_with_global_shift() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 2000.0, "Test"));

        // Total delay 150ms = 100ms correlation + 50ms global shift
        let config = SyncConfig::time_based(150.0, 50.0);
        let sync = TimeBased;
        let result = sync.apply(&mut data, &config).unwrap();

        // Full 150ms applied
        assert!((data.events[0].start_ms - 1150.0).abs() < 0.001);

        // Pure correlation recorded
        let details = &result.details;
        assert!((details.audio_correlation_ms.unwrap() - 100.0).abs() < 0.001);
    }
}
