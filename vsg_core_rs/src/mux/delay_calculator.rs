// vsg_core_rs/src/mux/delay_calculator.rs
//
// Track delay calculation for mkvmerge muxing.
//
// Implements critical delay calculation rules for different track types and sources.

use std::collections::HashMap;

/// Track type enum for delay calculation
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TrackType {
    Video,
    Audio,
    Subtitles,
}

/// Calculate the effective delay for a track to be used in mkvmerge
///
/// CRITICAL DELAY RULES:
///
/// 1. Source 1 VIDEO:
///    - IGNORE container delays (playback artifacts, not real timing)
///    - ONLY apply global_shift to stay in sync
///    - Formula: global_shift
///
/// 2. Source 1 AUDIO:
///    - Each track has its own container delay (real timing offset)
///    - Preserve that delay and add global shift
///    - Formula: round(container_delay) + global_shift
///
/// 3. Stepping-adjusted subtitles:
///    - Delay is already baked into the subtitle file
///    - Return 0 to avoid double-applying
///
/// 4. Frame-adjusted subtitles:
///    - Frame-perfect sync already applied to subtitle file
///    - Return 0 to avoid double-applying
///
/// 5. All other tracks:
///    - Use pre-calculated correlation delay
///    - This includes Source 1 subtitles, other source audio/video/subtitles
///    - Formula: round(source_delays_ms[source_key])
///
/// # Arguments
/// * `track_type` - Type of track (Video, Audio, Subtitles)
/// * `source_key` - Source identifier (e.g., "Source 1", "Source 2")
/// * `container_delay_ms` - Container delay from track properties
/// * `global_shift_ms` - Global shift to apply to all tracks
/// * `source_delays_ms` - Map of source keys to correlation delays
/// * `stepping_adjusted` - Whether stepping correction was applied
/// * `frame_adjusted` - Whether frame-perfect sync was applied
///
/// # Returns
/// Delay in milliseconds (signed integer)
///
/// # Examples
/// ```
/// // Source 1 video: only global shift
/// assert_eq!(calculate_track_delay(
///     TrackType::Video, "Source 1", 100, 500, &HashMap::new(), false, false
/// ), 500);
///
/// // Source 1 audio: container delay + global shift
/// assert_eq!(calculate_track_delay(
///     TrackType::Audio, "Source 1", 100, 500, &HashMap::new(), false, false
/// ), 600);
///
/// // Stepping-adjusted subtitle: return 0
/// assert_eq!(calculate_track_delay(
///     TrackType::Subtitles, "Source 1", 0, 500, &HashMap::new(), true, false
/// ), 0);
/// ```
pub fn calculate_track_delay(
    track_type: TrackType,
    source_key: &str,
    container_delay_ms: i32,
    global_shift_ms: i32,
    source_delays_ms: &HashMap<String, i32>,
    stepping_adjusted: bool,
    frame_adjusted: bool,
) -> i32 {
    // CRITICAL: Source 1 AUDIO - Preserve container delays + add global shift
    if source_key == "Source 1" && track_type == TrackType::Audio {
        // Use round() for proper rounding of negative values
        // int() truncates toward zero: int(-1001.825) = -1001 (WRONG)
        // round() rounds to nearest: round(-1001.825) = -1002 (CORRECT)
        let container_delay = container_delay_ms; // Already rounded from container
        let final_delay = container_delay + global_shift_ms;
        return final_delay;
    }

    // CRITICAL: Source 1 VIDEO - ONLY apply global shift (IGNORE container delays)
    // Video defines the timeline - we don't preserve its container delays
    if source_key == "Source 1" && track_type == TrackType::Video {
        return global_shift_ms;
    }

    // SPECIAL CASE: Stepping-adjusted subtitles
    // If subtitle timestamps were already adjusted for stepping corrections,
    // the base delay + stepping offsets are baked into the subtitle file.
    // Don't apply additional delay via mkvmerge to avoid double-applying.
    if track_type == TrackType::Subtitles && stepping_adjusted {
        return 0;
    }

    // SPECIAL CASE: Frame-adjusted subtitles
    // If subtitle timestamps were already adjusted with frame-perfect sync,
    // the delay is baked into the subtitle file with frame-snapping applied.
    // Don't apply additional delay via mkvmerge to avoid double-applying.
    if track_type == TrackType::Subtitles && frame_adjusted {
        return 0;
    }

    // All other tracks: Use the correlation delay from analysis
    // This includes:
    // - Source 1 subtitles (delay is 0 + global shift)
    // - Audio/video from other sources (correlation delay + global shift)
    // - Subtitles from other sources (correlation delay + global shift)
    let delay = source_delays_ms.get(source_key).copied().unwrap_or(0);

    // Use round() for proper rounding of negative values (safety for future refactoring)
    // In practice, this value should already be rounded from the analysis phase
    delay
}

/// Build mkvmerge sync token
///
/// CRITICAL FORMAT: Delays must be signed format with explicit '+' or '-'
/// - Positive: "+500" (not "500")
/// - Negative: "-500"
/// - Zero: "+0" (Python's {:+d} format adds '+' even for zero)
///
/// # Arguments
/// * `track_idx` - Track index in mkvmerge (usually 0 for single-track inputs)
/// * `delay_ms` - Delay in milliseconds (can be negative)
///
/// # Returns
/// Vec of tokens: ["--sync", "0:+500"]
///
/// # Examples
/// ```
/// assert_eq!(build_sync_token(0, 500), vec!["--sync", "0:+500"]);
/// assert_eq!(build_sync_token(0, -500), vec!["--sync", "0:-500"]);
/// assert_eq!(build_sync_token(0, 0), vec!["--sync", "0:+0"]);
/// ```
pub fn build_sync_token(track_idx: u32, delay_ms: i32) -> Vec<String> {
    vec![
        "--sync".to_string(),
        format!("{}:{:+}", track_idx, delay_ms),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    // ========================================================================
    // Source 1 VIDEO tests
    // ========================================================================

    #[test]
    fn test_source1_video_only_global_shift() {
        let source_delays = HashMap::new();

        // CRITICAL: Video ignores container delay
        let result = calculate_track_delay(
            TrackType::Video,
            "Source 1",
            100,  // container delay - should be IGNORED
            500,  // global shift
            &source_delays,
            false,
            false,
        );

        assert_eq!(result, 500); // Only global shift, container delay ignored
    }

    #[test]
    fn test_source1_video_negative_global_shift() {
        let source_delays = HashMap::new();

        let result = calculate_track_delay(
            TrackType::Video,
            "Source 1",
            100,
            -200,  // negative global shift
            &source_delays,
            false,
            false,
        );

        assert_eq!(result, -200);
    }

    // ========================================================================
    // Source 1 AUDIO tests
    // ========================================================================

    #[test]
    fn test_source1_audio_container_plus_global() {
        let source_delays = HashMap::new();

        // CRITICAL: Audio uses container delay + global shift
        let result = calculate_track_delay(
            TrackType::Audio,
            "Source 1",
            100,  // container delay
            500,  // global shift
            &source_delays,
            false,
            false,
        );

        assert_eq!(result, 600); // 100 + 500
    }

    #[test]
    fn test_source1_audio_negative_container() {
        let source_delays = HashMap::new();

        let result = calculate_track_delay(
            TrackType::Audio,
            "Source 1",
            -50,  // negative container delay
            500,
            &source_delays,
            false,
            false,
        );

        assert_eq!(result, 450); // -50 + 500
    }

    #[test]
    fn test_source1_audio_both_negative() {
        let source_delays = HashMap::new();

        let result = calculate_track_delay(
            TrackType::Audio,
            "Source 1",
            -100,
            -200,
            &source_delays,
            false,
            false,
        );

        assert_eq!(result, -300); // -100 + -200
    }

    // ========================================================================
    // Stepping-adjusted subtitle tests
    // ========================================================================

    #[test]
    fn test_stepping_adjusted_subtitle_returns_zero() {
        let source_delays = HashMap::new();

        // CRITICAL: Stepping-adjusted subtitles return 0 (delay baked in)
        let result = calculate_track_delay(
            TrackType::Subtitles,
            "Source 1",
            0,
            500,  // global shift should be ignored
            &source_delays,
            true,  // stepping_adjusted
            false,
        );

        assert_eq!(result, 0);
    }

    #[test]
    fn test_stepping_adjusted_other_source() {
        let mut source_delays = HashMap::new();
        source_delays.insert("Source 2".to_string(), 1000);

        // Stepping-adjusted applies to all sources
        let result = calculate_track_delay(
            TrackType::Subtitles,
            "Source 2",
            0,
            500,
            &source_delays,
            true,  // stepping_adjusted
            false,
        );

        assert_eq!(result, 0);
    }

    // ========================================================================
    // Frame-adjusted subtitle tests
    // ========================================================================

    #[test]
    fn test_frame_adjusted_subtitle_returns_zero() {
        let source_delays = HashMap::new();

        // CRITICAL: Frame-adjusted subtitles return 0 (delay baked in)
        let result = calculate_track_delay(
            TrackType::Subtitles,
            "Source 1",
            0,
            500,
            &source_delays,
            false,
            true,  // frame_adjusted
        );

        assert_eq!(result, 0);
    }

    // ========================================================================
    // Other source tests
    // ========================================================================

    #[test]
    fn test_source2_audio_uses_correlation_delay() {
        let mut source_delays = HashMap::new();
        source_delays.insert("Source 2".to_string(), 1500);

        let result = calculate_track_delay(
            TrackType::Audio,
            "Source 2",
            0,    // container delay ignored for other sources
            500,  // global shift already included in correlation delay
            &source_delays,
            false,
            false,
        );

        assert_eq!(result, 1500); // Uses correlation delay
    }

    #[test]
    fn test_source1_subtitle_uses_correlation_delay() {
        let mut source_delays = HashMap::new();
        source_delays.insert("Source 1".to_string(), 0);  // Source 1 subtitles typically have 0

        let result = calculate_track_delay(
            TrackType::Subtitles,
            "Source 1",
            0,
            500,
            &source_delays,
            false,
            false,
        );

        assert_eq!(result, 0);
    }

    #[test]
    fn test_missing_source_key_defaults_to_zero() {
        let source_delays = HashMap::new();

        let result = calculate_track_delay(
            TrackType::Audio,
            "Source 99",  // Not in map
            0,
            500,
            &source_delays,
            false,
            false,
        );

        assert_eq!(result, 0); // Defaults to 0 when source not found
    }

    // ========================================================================
    // Sync token building tests
    // ========================================================================

    #[test]
    fn test_build_sync_token_positive() {
        let tokens = build_sync_token(0, 500);
        assert_eq!(tokens, vec!["--sync", "0:+500"]);
    }

    #[test]
    fn test_build_sync_token_negative() {
        let tokens = build_sync_token(0, -500);
        assert_eq!(tokens, vec!["--sync", "0:-500"]);
    }

    #[test]
    fn test_build_sync_token_zero() {
        let tokens = build_sync_token(0, 0);
        // CRITICAL: Python's {:+d} format adds '+' even for zero
        assert_eq!(tokens, vec!["--sync", "0:+0"]);
    }

    #[test]
    fn test_build_sync_token_different_track_idx() {
        let tokens = build_sync_token(2, 1000);
        assert_eq!(tokens, vec!["--sync", "2:+1000"]);
    }
}
