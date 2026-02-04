//! Frame/time conversion functions.
//!
//! Pure functions for converting between frame numbers and timestamps.
//! All functions are deterministic and have no side effects.
//!
//! # Timing Modes
//!
//! - **Floor**: Frame START - stable, deterministic, preferred for sync math
//! - **Middle**: Middle of frame window - balanced approach
//! - **Aegisub**: Matches Aegisub's algorithm - ceil to centisecond

/// Small epsilon for floating-point comparisons.
const EPSILON: f64 = 1e-6;

// ============================================================================
// MODE 0: FRAME START (Floor-based, Deterministic)
// ============================================================================

/// Convert timestamp to frame number using FLOOR with epsilon protection.
///
/// This gives the frame that is currently displaying at the given time.
/// This is the preferred method for sync math because:
/// - Deterministic (no rounding ambiguity at boundaries)
/// - Stable under floating point drift
/// - Maps to actual frame boundaries (frame N starts at N * frame_duration)
///
/// # Arguments
/// * `time_ms` - Timestamp in milliseconds
/// * `fps` - Frame rate (e.g., 23.976)
///
/// # Returns
/// Frame number (which frame is displaying at this time)
///
/// # Examples
/// ```
/// use vsg_core::subtitles::frame_utils::timing::time_to_frame_floor;
///
/// // At 23.976 fps (frame_duration = 41.708ms):
/// assert_eq!(time_to_frame_floor(0.0, 23.976), 0);
/// assert_eq!(time_to_frame_floor(41.707, 23.976), 0);  // Still in frame 0
/// assert_eq!(time_to_frame_floor(41.709, 23.976), 1);  // Frame 1 starts
/// assert_eq!(time_to_frame_floor(1001.0, 23.976), 24); // Frame 24
/// ```
pub fn time_to_frame_floor(time_ms: f64, fps: f64) -> i32 {
    let frame_duration_ms = 1000.0 / fps;
    // Add small epsilon to protect against FP errors where time_ms is slightly under frame boundary
    ((time_ms + EPSILON) / frame_duration_ms) as i32
}

/// Convert frame number to its START timestamp (exact, no rounding).
///
/// This is the preferred method for sync math because:
/// - Frame N starts at exactly N * frame_duration
/// - No rounding (exact calculation)
/// - Guarantees frame-aligned timing
///
/// # Arguments
/// * `frame_num` - Frame number
/// * `fps` - Frame rate (e.g., 23.976)
///
/// # Returns
/// Timestamp in milliseconds (frame START time, as float for precision)
///
/// # Examples
/// ```
/// use vsg_core::subtitles::frame_utils::timing::frame_to_time_floor;
///
/// // At 23.976 fps (frame_duration = 41.708ms):
/// assert!((frame_to_time_floor(0, 23.976) - 0.0).abs() < 0.001);
/// assert!((frame_to_time_floor(1, 23.976) - 41.708).abs() < 0.01);
/// assert!((frame_to_time_floor(24, 23.976) - 1001.0).abs() < 0.1);
/// ```
pub fn frame_to_time_floor(frame_num: i32, fps: f64) -> f64 {
    let frame_duration_ms = 1000.0 / fps;
    frame_num as f64 * frame_duration_ms
}

// ============================================================================
// MODE 1: MIDDLE OF FRAME
// ============================================================================

/// Convert timestamp to frame number, accounting for +0.5 offset.
///
/// Uses the middle of the frame window for rounding decisions.
///
/// # Arguments
/// * `time_ms` - Timestamp in milliseconds
/// * `fps` - Frame rate (e.g., 23.976)
///
/// # Returns
/// Frame number
pub fn time_to_frame_middle(time_ms: f64, fps: f64) -> i32 {
    let frame_duration_ms = 1000.0 / fps;
    (time_ms / frame_duration_ms - 0.5).round() as i32
}

/// Convert frame to timestamp targeting middle of frame window.
///
/// Targets the middle of the frame's display window with +0.5 offset.
///
/// # Example at 23.976 fps
/// - Frame 24 displays from 1001.001ms to 1042.709ms
/// - Calculation: 24.5 × 41.708 = 1022ms
/// - After centisecond rounding: 1020ms (safely in frame 24)
///
/// # Arguments
/// * `frame_num` - Frame number
/// * `fps` - Frame rate (e.g., 23.976)
///
/// # Returns
/// Timestamp in milliseconds (rounded to integer)
pub fn frame_to_time_middle(frame_num: i32, fps: f64) -> i32 {
    let frame_duration_ms = 1000.0 / fps;
    ((frame_num as f64 + 0.5) * frame_duration_ms).round() as i32
}

// ============================================================================
// MODE 2: AEGISUB-STYLE (Ceil to Centisecond)
// ============================================================================

/// Convert timestamp to frame using floor division.
///
/// Matches Aegisub's time-to-frame conversion.
///
/// # Arguments
/// * `time_ms` - Timestamp in milliseconds
/// * `fps` - Frame rate
///
/// # Returns
/// Frame number
pub fn time_to_frame_aegisub(time_ms: f64, fps: f64) -> i32 {
    let frame_duration_ms = 1000.0 / fps;
    (time_ms / frame_duration_ms) as i32
}

/// Convert frame to timestamp using Aegisub's algorithm.
///
/// Matches Aegisub's algorithm: Calculate exact frame start, then round UP
/// to the next centisecond to ensure timestamp falls within the frame.
///
/// # Example at 23.976 fps
/// - Frame 24 starts at 1001.001ms
/// - Exact calculation: 24 × 41.708 = 1001.001ms
/// - Round UP to next centisecond: ceil(1001.001 / 10) × 10 = 1010ms
/// - Result: 1010ms (safely in frame 24: 1001-1043ms)
///
/// # Arguments
/// * `frame_num` - Frame number
/// * `fps` - Frame rate
///
/// # Returns
/// Timestamp in milliseconds (ceiled to centisecond)
pub fn frame_to_time_aegisub(frame_num: i32, fps: f64) -> i32 {
    let frame_duration_ms = 1000.0 / fps;
    let exact_time_ms = frame_num as f64 * frame_duration_ms;

    // Round UP to next centisecond (ASS format precision)
    // This ensures the timestamp is guaranteed to fall within the frame
    let centiseconds = (exact_time_ms / 10.0).ceil();
    (centiseconds * 10.0) as i32
}

// ============================================================================
// UTILITY FUNCTIONS
// ============================================================================

/// Calculate frame duration in milliseconds.
///
/// # Arguments
/// * `fps` - Frame rate
///
/// # Returns
/// Frame duration in milliseconds
#[inline]
pub fn frame_duration_ms(fps: f64) -> f64 {
    1000.0 / fps
}

/// Convert FPS to fraction for NTSC rates.
///
/// NTSC standards use fractional rates (N×1000/1001) to avoid color/audio drift.
///
/// # Arguments
/// * `fps` - Frame rate
///
/// # Returns
/// (numerator, denominator) tuple
pub fn fps_to_fraction(fps: f64) -> (u32, u32) {
    // Common NTSC framerates
    if (fps - 23.976).abs() < 0.01 {
        (24000, 1001) // 23.976fps - NTSC film
    } else if (fps - 29.97).abs() < 0.01 {
        (30000, 1001) // 29.97fps - NTSC video
    } else if (fps - 59.94).abs() < 0.01 {
        (60000, 1001) // 59.94fps - NTSC high fps
    } else if (fps - 24.0).abs() < 0.01 {
        (24, 1)
    } else if (fps - 25.0).abs() < 0.01 {
        (25, 1) // PAL
    } else if (fps - 30.0).abs() < 0.01 {
        (30, 1)
    } else if (fps - 50.0).abs() < 0.01 {
        (50, 1)
    } else if (fps - 60.0).abs() < 0.01 {
        (60, 1)
    } else {
        // Generic: multiply by 1000 and use that
        ((fps * 1000.0).round() as u32, 1000)
    }
}

/// Parse FPS fraction string (e.g., "24000/1001") to float.
///
/// # Arguments
/// * `s` - Fraction string like "24000/1001" or plain number like "25"
///
/// # Returns
/// FPS as float, or None if parsing fails
pub fn parse_fps_fraction(s: &str) -> Option<f64> {
    if s.contains('/') {
        let parts: Vec<&str> = s.split('/').collect();
        if parts.len() == 2 {
            let num: f64 = parts[0].trim().parse().ok()?;
            let denom: f64 = parts[1].trim().parse().ok()?;
            if denom != 0.0 {
                return Some(num / denom);
            }
        }
        None
    } else {
        s.trim().parse().ok()
    }
}

/// Generate candidate frame offsets centered on a correlation value.
///
/// # Arguments
/// * `correlation_frames` - Audio correlation converted to frames (can be fractional)
/// * `search_range_frames` - How many frames on each side to search
///
/// # Returns
/// Sorted list of integer frame offsets to test
pub fn generate_frame_candidates(correlation_frames: f64, search_range_frames: i32) -> Vec<i32> {
    let mut candidates = std::collections::HashSet::new();

    // Round correlation to nearest frame
    let base_frame = correlation_frames.round() as i32;

    // Always include zero (in case correlation is just wrong)
    candidates.insert(0);

    // Search window around correlation
    for delta in -search_range_frames..=search_range_frames {
        candidates.insert(base_frame + delta);
    }

    let mut result: Vec<i32> = candidates.into_iter().collect();
    result.sort();
    result
}

/// Select checkpoint times distributed across video duration.
///
/// Uses percentage-based positions, avoiding very start/end of video.
///
/// # Arguments
/// * `duration_ms` - Video duration in milliseconds
/// * `num_checkpoints` - Number of checkpoints to generate
///
/// # Returns
/// List of checkpoint times in milliseconds
pub fn select_checkpoint_times(duration_ms: f64, num_checkpoints: usize) -> Vec<f64> {
    // Use percentage-based positions (avoiding very start/end)
    let positions = [15, 30, 50, 70, 85];

    positions
        .iter()
        .take(num_checkpoints)
        .map(|&pos| duration_ms * pos as f64 / 100.0)
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_time_to_frame_floor() {
        let fps = 23.976;

        assert_eq!(time_to_frame_floor(0.0, fps), 0);
        assert_eq!(time_to_frame_floor(41.0, fps), 0); // Still in frame 0
        assert_eq!(time_to_frame_floor(42.0, fps), 1); // Frame 1
        assert_eq!(time_to_frame_floor(1001.0, fps), 24); // Frame 24
    }

    #[test]
    fn test_frame_to_time_floor() {
        let fps = 23.976;

        assert!((frame_to_time_floor(0, fps) - 0.0).abs() < 0.001);
        assert!((frame_to_time_floor(24, fps) - 1001.0).abs() < 0.1);
    }

    #[test]
    fn test_aegisub_style() {
        let fps = 23.976;

        // Frame 24 should give 1010ms (ceiled to centisecond)
        let time = frame_to_time_aegisub(24, fps);
        assert_eq!(time, 1010);
    }

    #[test]
    fn test_fps_to_fraction() {
        assert_eq!(fps_to_fraction(23.976), (24000, 1001));
        assert_eq!(fps_to_fraction(29.97), (30000, 1001));
        assert_eq!(fps_to_fraction(25.0), (25, 1));
    }

    #[test]
    fn test_parse_fps_fraction() {
        assert!((parse_fps_fraction("24000/1001").unwrap() - 23.976).abs() < 0.001);
        assert!((parse_fps_fraction("25").unwrap() - 25.0).abs() < 0.001);
        assert!(parse_fps_fraction("invalid").is_none());
    }

    #[test]
    fn test_generate_frame_candidates() {
        // Correlation at 2.3 frames with range 3
        let candidates = generate_frame_candidates(2.3, 3);

        // Should include 0 (always) and -1 to 5 (2 ± 3)
        assert!(candidates.contains(&0));
        assert!(candidates.contains(&2));
        assert!(candidates.contains(&-1));
        assert!(candidates.contains(&5));
    }

    #[test]
    fn test_select_checkpoint_times() {
        let duration = 1000000.0; // 1000 seconds
        let checkpoints = select_checkpoint_times(duration, 5);

        assert_eq!(checkpoints.len(), 5);
        assert!((checkpoints[0] - 150000.0).abs() < 1.0); // 15%
        assert!((checkpoints[2] - 500000.0).abs() < 1.0); // 50%
    }

    #[test]
    fn test_roundtrip_floor() {
        let fps = 23.976;

        for frame in 0..100 {
            let time = frame_to_time_floor(frame, fps);
            let recovered = time_to_frame_floor(time, fps);
            assert_eq!(frame, recovered, "Roundtrip failed for frame {}", frame);
        }
    }
}
