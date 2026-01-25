//! Centralized delay calculation logic.
//!
//! This module is the **SINGLE SOURCE OF TRUTH** for delay calculations.
//! All delay math happens here - no scattered `+delay` or `-delay` elsewhere.
//!
//! # Delay Calculation Rules
//!
//! ## Source 1 (Reference Source)
//!
//! Source 1 is the reference - its video track defines the output timeline.
//!
//! - **Video**: `global_shift_ms` only
//!   - Video defines the timeline, so no additional delay needed
//!   - Global shift keeps all tracks non-negative
//!
//! - **Audio**: `relative_container_delay + global_shift_ms`
//!   - `relative_container_delay = audio_container_delay - video_container_delay`
//!   - This preserves Source 1's original internal A/V sync
//!   - Example: If audio starts 50ms after video in Source 1, that offset is kept
//!
//! - **Subtitles**: `global_shift_ms` only
//!   - Subtitles are aligned to video, not audio
//!
//! ## Source 2/3 (Synced Sources)
//!
//! These sources have been sync-analyzed against Source 1.
//!
//! - **All tracks**: `source_delays_ms[source_key]`
//!   - The correlation delay already includes:
//!     - The sync offset found by analysis
//!     - The global shift applied uniformly
//!   - Container delays from Source 2/3 are NOT used
//!     (correlation already accounts for their timing)
//!
//! ## Special Cases
//!
//! - **Stepping-adjusted subtitles**: `delay = 0`
//!   - When subtitles are pre-adjusted for stepping, the delay is embedded in timestamps
//!
//! - **External subtitles**: `source_delays_ms[sync_to]`
//!   - External subs sync to a specific source, use that source's delay
//!
//! # Global Shift
//!
//! The global shift is calculated during analysis to make all delays non-negative.
//! This is required because some players don't handle negative container delays.
//!
//! ```text
//! most_negative_delay = min(all_source_delays)
//! if most_negative_delay < 0:
//!     global_shift = abs(most_negative_delay)
//! else:
//!     global_shift = 0
//! ```
//!
//! The global shift is applied to ALL tracks uniformly, preserving relative timing.

use std::collections::HashMap;

use crate::extraction::ContainerInfo;
use crate::models::{Delays, TrackType};

/// Input for delay calculation for a single track.
#[derive(Debug, Clone)]
pub struct DelayInput<'a> {
    /// Source key ("Source 1", "Source 2", etc.)
    pub source_key: &'a str,
    /// Track ID within the source.
    pub track_id: usize,
    /// Type of track (Video, Audio, Subtitles).
    pub track_type: TrackType,
    /// Whether this subtitle was stepping-adjusted (delay embedded in file).
    pub stepping_adjusted: bool,
    /// For external subtitles, which source to sync to.
    pub sync_to: Option<&'a str>,
}

/// Context for delay calculations.
#[derive(Debug)]
pub struct DelayContext<'a> {
    /// Calculated sync delays from analysis.
    pub delays: &'a Delays,
    /// Container info for each source.
    pub container_info: &'a HashMap<String, ContainerInfo>,
}

impl<'a> DelayContext<'a> {
    /// Create a new delay context.
    pub fn new(
        delays: &'a Delays,
        container_info: &'a HashMap<String, ContainerInfo>,
    ) -> Self {
        Self {
            delays,
            container_info,
        }
    }
}

/// Calculate the effective delay for a track in the merge.
///
/// This is the main entry point for delay calculation. Call this for each
/// track to get the delay value to pass to mkvmerge's `--sync` option.
///
/// # Arguments
///
/// * `input` - Information about the track
/// * `ctx` - Context containing delays and container info
///
/// # Returns
///
/// The delay in milliseconds to apply to this track.
pub fn calculate_effective_delay(input: &DelayInput, ctx: &DelayContext) -> i64 {
    let source_key = input.source_key;
    let global_shift = ctx.delays.global_shift_ms;

    // Handle stepping-adjusted subtitles first
    if input.stepping_adjusted {
        // Delay is already embedded in subtitle timestamps
        return 0;
    }

    // Handle external subtitles
    if let Some(sync_to) = input.sync_to {
        // Use the delay of the source this subtitle syncs to
        return ctx
            .delays
            .source_delays_ms
            .get(sync_to)
            .copied()
            .unwrap_or(global_shift);
    }

    match (input.track_type, source_key) {
        // =====================================================================
        // Source 1 (Reference Source)
        // =====================================================================

        // Source 1 VIDEO: global shift only
        // Video defines the timeline, no additional delay needed
        (TrackType::Video, "Source 1") => global_shift,

        // Source 1 AUDIO: relative container delay + global shift
        // Preserves Source 1's original internal A/V sync
        (TrackType::Audio, "Source 1") => {
            let relative_delay = ctx
                .container_info
                .get("Source 1")
                .map(|info| info.relative_audio_delay(input.track_id))
                .unwrap_or(0);

            relative_delay + global_shift
        }

        // Source 1 SUBTITLES: global shift only
        // Subtitles align to video, not audio
        (TrackType::Subtitles, "Source 1") => global_shift,

        // =====================================================================
        // Source 2/3 (Synced Sources)
        // =====================================================================

        // All other sources: use the correlation delay
        // This already includes the global shift
        _ => ctx
            .delays
            .source_delays_ms
            .get(source_key)
            .copied()
            .unwrap_or(0),
    }
}

/// Calculate the global shift needed to make all delays non-negative.
///
/// # Arguments
///
/// * `source_delays_raw` - Map of source keys to raw delay values (before global shift)
///
/// # Returns
///
/// The global shift to apply (always >= 0).
pub fn calculate_global_shift(source_delays_raw: &HashMap<String, f64>) -> i64 {
    // Find the most negative delay
    let min_delay = source_delays_raw
        .values()
        .copied()
        .fold(0.0f64, f64::min);

    if min_delay < 0.0 {
        // Round up to ensure no negative values remain
        (-min_delay).ceil() as i64
    } else {
        0
    }
}

/// Apply global shift to raw delays and return final delays.
///
/// # Arguments
///
/// * `source_delays_raw` - Map of source keys to raw delay values (before global shift)
///
/// # Returns
///
/// `Delays` struct with both raw and rounded values, plus global shift.
pub fn finalize_delays(source_delays_raw: HashMap<String, f64>) -> Delays {
    let global_shift = calculate_global_shift(&source_delays_raw);
    let global_shift_f64 = global_shift as f64;

    let mut delays = Delays::new();
    delays.global_shift_ms = global_shift;
    delays.raw_global_shift_ms = global_shift_f64;

    for (source_key, raw_delay) in source_delays_raw {
        let shifted_raw = raw_delay + global_shift_f64;
        delays.raw_source_delays_ms.insert(source_key.clone(), shifted_raw);
        delays
            .source_delays_ms
            .insert(source_key, shifted_raw.round() as i64);
    }

    // Ensure Source 1 has an entry (with just global shift)
    if !delays.source_delays_ms.contains_key("Source 1") {
        delays.source_delays_ms.insert("Source 1".to_string(), global_shift);
        delays.raw_source_delays_ms.insert("Source 1".to_string(), global_shift_f64);
    }

    delays
}

/// Format a delay for logging.
pub fn format_delay(delay_ms: i64) -> String {
    if delay_ms == 0 {
        "0ms".to_string()
    } else if delay_ms > 0 {
        format!("+{}ms", delay_ms)
    } else {
        format!("{}ms", delay_ms)
    }
}

/// Log the delay calculation for debugging.
pub fn log_delay_calculation(
    input: &DelayInput,
    ctx: &DelayContext,
    result: i64,
) -> String {
    let source = input.source_key;
    let track_type = format!("{:?}", input.track_type);

    if input.stepping_adjusted {
        return format!(
            "{} {} track {} -> {} (stepping-adjusted, embedded in file)",
            source, track_type, input.track_id, format_delay(result)
        );
    }

    if let Some(sync_to) = input.sync_to {
        return format!(
            "{} {} track {} -> {} (external, synced to {})",
            source, track_type, input.track_id, format_delay(result), sync_to
        );
    }

    let global_shift = ctx.delays.global_shift_ms;

    match (input.track_type, input.source_key) {
        (TrackType::Video, "Source 1") => {
            format!(
                "{} {} track {} -> {} (global_shift={})",
                source, track_type, input.track_id, format_delay(result), global_shift
            )
        }
        (TrackType::Audio, "Source 1") => {
            let container_delay = ctx
                .container_info
                .get("Source 1")
                .map(|info| info.relative_audio_delay(input.track_id))
                .unwrap_or(0);
            format!(
                "{} {} track {} -> {} (container_relative={}, global_shift={})",
                source, track_type, input.track_id, format_delay(result),
                format_delay(container_delay), global_shift
            )
        }
        (TrackType::Subtitles, "Source 1") => {
            format!(
                "{} {} track {} -> {} (global_shift={})",
                source, track_type, input.track_id, format_delay(result), global_shift
            )
        }
        _ => {
            let source_delay = ctx.delays.source_delays_ms.get(source).copied().unwrap_or(0);
            format!(
                "{} {} track {} -> {} (correlation={}, includes global_shift={})",
                source, track_type, input.track_id, format_delay(result),
                format_delay(source_delay), global_shift
            )
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    fn create_test_delays() -> Delays {
        let mut delays = Delays::new();
        delays.global_shift_ms = 100;
        delays.source_delays_ms.insert("Source 1".to_string(), 100); // 0 + global shift
        delays.source_delays_ms.insert("Source 2".to_string(), 250); // 150 + global shift
        delays.source_delays_ms.insert("Source 3".to_string(), 50);  // -50 + global shift
        delays
    }

    fn create_test_container_info() -> HashMap<String, ContainerInfo> {
        let mut info = HashMap::new();

        let mut source1 = ContainerInfo::new("Source 1", PathBuf::from("/test1.mkv"));
        source1.video_delay_ms = 100;
        source1.track_delays_ms.insert(0, 100); // Video
        source1.track_delays_ms.insert(1, 150); // Audio - 50ms behind video
        source1.track_delays_ms.insert(2, 100); // Subtitle - aligned with video
        info.insert("Source 1".to_string(), source1);

        info
    }

    #[test]
    fn test_source1_video_delay() {
        let delays = create_test_delays();
        let container_info = create_test_container_info();
        let ctx = DelayContext::new(&delays, &container_info);

        let input = DelayInput {
            source_key: "Source 1",
            track_id: 0,
            track_type: TrackType::Video,
            stepping_adjusted: false,
            sync_to: None,
        };

        // Should be just global shift
        assert_eq!(calculate_effective_delay(&input, &ctx), 100);
    }

    #[test]
    fn test_source1_audio_delay() {
        let delays = create_test_delays();
        let container_info = create_test_container_info();
        let ctx = DelayContext::new(&delays, &container_info);

        let input = DelayInput {
            source_key: "Source 1",
            track_id: 1,
            track_type: TrackType::Audio,
            stepping_adjusted: false,
            sync_to: None,
        };

        // Should be relative container delay (50) + global shift (100) = 150
        assert_eq!(calculate_effective_delay(&input, &ctx), 150);
    }

    #[test]
    fn test_source1_subtitle_delay() {
        let delays = create_test_delays();
        let container_info = create_test_container_info();
        let ctx = DelayContext::new(&delays, &container_info);

        let input = DelayInput {
            source_key: "Source 1",
            track_id: 2,
            track_type: TrackType::Subtitles,
            stepping_adjusted: false,
            sync_to: None,
        };

        // Should be just global shift
        assert_eq!(calculate_effective_delay(&input, &ctx), 100);
    }

    #[test]
    fn test_source2_audio_delay() {
        let delays = create_test_delays();
        let container_info = create_test_container_info();
        let ctx = DelayContext::new(&delays, &container_info);

        let input = DelayInput {
            source_key: "Source 2",
            track_id: 1,
            track_type: TrackType::Audio,
            stepping_adjusted: false,
            sync_to: None,
        };

        // Should use correlation delay (which already includes global shift)
        assert_eq!(calculate_effective_delay(&input, &ctx), 250);
    }

    #[test]
    fn test_stepping_adjusted_subtitle() {
        let delays = create_test_delays();
        let container_info = create_test_container_info();
        let ctx = DelayContext::new(&delays, &container_info);

        let input = DelayInput {
            source_key: "Source 2",
            track_id: 3,
            track_type: TrackType::Subtitles,
            stepping_adjusted: true,
            sync_to: None,
        };

        // Should be 0 (delay embedded in file)
        assert_eq!(calculate_effective_delay(&input, &ctx), 0);
    }

    #[test]
    fn test_external_subtitle() {
        let delays = create_test_delays();
        let container_info = create_test_container_info();
        let ctx = DelayContext::new(&delays, &container_info);

        let input = DelayInput {
            source_key: "External",
            track_id: 0,
            track_type: TrackType::Subtitles,
            stepping_adjusted: false,
            sync_to: Some("Source 2"),
        };

        // Should use Source 2's delay
        assert_eq!(calculate_effective_delay(&input, &ctx), 250);
    }

    #[test]
    fn test_calculate_global_shift() {
        // No negative delays
        let mut delays = HashMap::new();
        delays.insert("Source 2".to_string(), 100.0);
        delays.insert("Source 3".to_string(), 50.0);
        assert_eq!(calculate_global_shift(&delays), 0);

        // Negative delay present
        let mut delays = HashMap::new();
        delays.insert("Source 2".to_string(), 100.0);
        delays.insert("Source 3".to_string(), -200.5);
        assert_eq!(calculate_global_shift(&delays), 201); // Rounded up

        // All negative
        let mut delays = HashMap::new();
        delays.insert("Source 2".to_string(), -50.0);
        delays.insert("Source 3".to_string(), -100.0);
        assert_eq!(calculate_global_shift(&delays), 100);
    }

    #[test]
    fn test_finalize_delays() {
        let mut raw = HashMap::new();
        raw.insert("Source 2".to_string(), -100.5);
        raw.insert("Source 3".to_string(), 50.0);

        let delays = finalize_delays(raw);

        // Global shift should make most negative non-negative
        assert_eq!(delays.global_shift_ms, 101); // ceil(100.5)

        // Source 2: -100.5 + 101 = 0.5 -> rounded to 1
        assert_eq!(delays.source_delays_ms.get("Source 2"), Some(&1));

        // Source 3: 50 + 101 = 151
        assert_eq!(delays.source_delays_ms.get("Source 3"), Some(&151));

        // Source 1 should be added with just global shift
        assert_eq!(delays.source_delays_ms.get("Source 1"), Some(&101));
    }
}
