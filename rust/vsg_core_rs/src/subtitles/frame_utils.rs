// vsg_core_rs/src/subtitles/frame_utils.rs
//
// Frame timing and conversion utilities for subtitle synchronization.
//
// Contains pure computational functions for frame/time conversions.
// VFR handling and video-specific functions remain in Python (videotimestamps library).

/// CRITICAL: Epsilon value for floating point protection
/// Must match Python implementation exactly
const EPSILON: f64 = 1e-6;

/// CRITICAL: Centisecond precision (ASS subtitle format)
const CENTISECOND_MS: f64 = 10.0;

// ============================================================================
// MODE 0: FRAME START (For Correlation-Frame-Snap - STABLE & DETERMINISTIC)
// ============================================================================

/// MODE 0: Frame START (stable, deterministic).
///
/// Convert timestamp to frame number using FLOOR with epsilon protection.
/// This gives the frame that is currently displaying at the given time.
///
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
/// # Examples at 23.976 fps (frame_duration = 41.708ms)
/// ```
/// time_to_frame_floor(0.0, 23.976) → 0
/// time_to_frame_floor(41.707, 23.976) → 0 (still in frame 0)
/// time_to_frame_floor(41.708, 23.976) → 1 (frame 1 starts)
/// time_to_frame_floor(1000.999, 23.976) → 23 (FP drift protected)
/// time_to_frame_floor(1001.0, 23.976) → 24
/// ```
///
/// # Critical Preservation
/// - EPSILON = 1e-6 exactly (protects against floating point errors)
/// - Uses floor() not round()
/// - Returns i64 to match Python int (can be negative for pre-roll)
pub fn time_to_frame_floor(time_ms: f64, fps: f64) -> i64 {
    let frame_duration_ms = 1000.0 / fps;
    // Add small epsilon to protect against FP errors where time_ms is slightly under frame boundary
    ((time_ms + EPSILON) / frame_duration_ms).floor() as i64
}

/// MODE 0: Frame START (stable, deterministic).
///
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
/// Timestamp in milliseconds (frame START time, as f64 for precision)
///
/// # Examples at 23.976 fps (frame_duration = 41.708ms)
/// ```
/// frame_to_time_floor(0, 23.976) → 0.0
/// frame_to_time_floor(1, 23.976) → 41.708
/// frame_to_time_floor(24, 23.976) → 1001.0
/// frame_to_time_floor(100, 23.976) → 4170.8
/// ```
///
/// # Critical Preservation
/// - No rounding, exact calculation
/// - Returns f64 for precision (not truncated to int)
pub fn frame_to_time_floor(frame_num: i64, fps: f64) -> f64 {
    let frame_duration_ms = 1000.0 / fps;
    frame_num as f64 * frame_duration_ms
}

// ============================================================================
// MODE 1: MIDDLE OF FRAME (Current Implementation)
// ============================================================================

/// MODE 1: Middle of frame window.
///
/// Convert timestamp to frame number, accounting for +0.5 offset.
///
/// # Arguments
/// * `time_ms` - Timestamp in milliseconds
/// * `fps` - Frame rate (e.g., 23.976)
///
/// # Returns
/// Frame number
///
/// # Critical Preservation
/// - Uses round() with -0.5 offset
/// - Python: round(time_ms / frame_duration_ms - 0.5)
/// - Python's round() uses "banker's rounding" (round half to even)
pub fn time_to_frame_middle(time_ms: f64, fps: f64) -> i64 {
    let frame_duration_ms = 1000.0 / fps;
    let value = time_ms / frame_duration_ms - 0.5;

    // Use Python's banker's rounding (round half to even)
    // This matches Python's built-in round() behavior
    python_round(value)
}

/// Python-compatible rounding (banker's rounding / round half to even)
///
/// Python's round() uses "round half to even" which means:
/// - round(0.5) = 0 (rounds to nearest even)
/// - round(1.5) = 2 (rounds to nearest even)
/// - round(-0.5) = 0 (rounds to nearest even)
/// - round(-1.5) = -2 (rounds to nearest even)
fn python_round(value: f64) -> i64 {
    let rounded = value.round();
    let floored = value.floor();
    let ceiled = value.ceil();

    // Check if we're exactly at the halfway point
    if (value - floored - 0.5).abs() < 1e-10 {
        // We're at X.5, use banker's rounding (round to even)
        if (floored as i64) % 2 == 0 {
            floored as i64
        } else {
            ceiled as i64
        }
    } else {
        rounded as i64
    }
}

/// MODE 1: Middle of frame window.
///
/// Targets the middle of the frame's display window with +0.5 offset.
///
/// Example at 23.976 fps:
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
///
/// # Critical Preservation
/// - Adds +0.5 offset to frame_num
/// - Rounds to nearest integer (not truncates)
/// - Python: int(round((frame_num + 0.5) * frame_duration_ms))
pub fn frame_to_time_middle(frame_num: i64, fps: f64) -> i64 {
    let frame_duration_ms = 1000.0 / fps;
    ((frame_num as f64 + 0.5) * frame_duration_ms).round() as i64
}

// ============================================================================
// MODE 2: AEGISUB-STYLE (Ceil to Centisecond)
// ============================================================================

/// MODE 2: Aegisub-style timing.
///
/// Convert timestamp to frame using floor division (which frame is currently displaying).
///
/// # Arguments
/// * `time_ms` - Timestamp in milliseconds
/// * `fps` - Frame rate
///
/// # Returns
/// Frame number
///
/// # Critical Preservation
/// - Uses floor division (int cast in Python)
/// - No epsilon adjustment
/// - Python: int(time_ms / frame_duration_ms)
pub fn time_to_frame_aegisub(time_ms: f64, fps: f64) -> i64 {
    let frame_duration_ms = 1000.0 / fps;
    (time_ms / frame_duration_ms).floor() as i64
}

/// MODE 2: Aegisub-style timing.
///
/// Matches Aegisub's algorithm: Calculate exact frame start, then round UP
/// to the next centisecond to ensure timestamp falls within the frame.
///
/// Example at 23.976 fps:
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
/// Timestamp in milliseconds
///
/// # Critical Preservation
/// - CRITICAL: Centisecond = 10ms (ASS subtitle format precision)
/// - Uses ceil() to round UP
/// - Ensures timestamp falls within frame boundary
/// - Python: math.ceil(exact_time_ms / 10) * 10
pub fn frame_to_time_aegisub(frame_num: i64, fps: f64) -> i64 {
    let frame_duration_ms = 1000.0 / fps;
    let exact_time_ms = frame_num as f64 * frame_duration_ms;

    // Round UP to next centisecond (ASS format precision)
    // This ensures the timestamp is guaranteed to fall within the frame
    let centiseconds = (exact_time_ms / CENTISECOND_MS).ceil() as i64;
    centiseconds * CENTISECOND_MS as i64
}

#[cfg(test)]
mod tests {
    use super::*;

    // Test constants
    const FPS_23976: f64 = 23.976;
    const FPS_25: f64 = 25.0;
    const FPS_29970: f64 = 29.970;

    // ========================================================================
    // MODE 0: Frame START tests
    // ========================================================================

    #[test]
    fn test_time_to_frame_floor_basics() {
        // At 23.976 fps, frame_duration = 41.70837504... ms
        // Frame 24 starts at 1001.001ms
        assert_eq!(time_to_frame_floor(0.0, FPS_23976), 0);
        assert_eq!(time_to_frame_floor(41.707, FPS_23976), 0); // Still in frame 0
        assert_eq!(time_to_frame_floor(41.708, FPS_23976), 0); // Still in frame 0 (duration is 41.70837...)
        assert_eq!(time_to_frame_floor(41.709, FPS_23976), 1); // Frame 1 starts
        assert_eq!(time_to_frame_floor(1000.999, FPS_23976), 23); // Still in frame 23
        assert_eq!(time_to_frame_floor(1001.0, FPS_23976), 23); // Still in frame 23 (frame 24 starts at 1001.001)
        assert_eq!(time_to_frame_floor(1001.002, FPS_23976), 24); // Frame 24
    }

    #[test]
    fn test_time_to_frame_floor_epsilon_protection() {
        // Epsilon protects against floating point errors
        // Without epsilon, 83.417 might round down to frame 1 instead of 2
        let result = time_to_frame_floor(83.417, FPS_23976);
        assert_eq!(result, 2); // Should be frame 2, not 1
    }

    #[test]
    fn test_frame_to_time_floor_basics() {
        // At 23.976 fps, frame_duration = 41.708ms
        assert_eq!(frame_to_time_floor(0, FPS_23976), 0.0);

        let t1 = frame_to_time_floor(1, FPS_23976);
        assert!((t1 - 41.708).abs() < 0.001);

        let t24 = frame_to_time_floor(24, FPS_23976);
        assert!((t24 - 1001.0).abs() < 0.1);

        let t100 = frame_to_time_floor(100, FPS_23976);
        assert!((t100 - 4170.8).abs() < 0.1);
    }

    #[test]
    fn test_mode0_roundtrip() {
        // Frame -> Time -> Frame should be stable
        for frame in [0, 1, 24, 100, 1000] {
            let time = frame_to_time_floor(frame, FPS_23976);
            let back = time_to_frame_floor(time, FPS_23976);
            assert_eq!(back, frame, "Roundtrip failed for frame {}", frame);
        }
    }

    // ========================================================================
    // MODE 1: Middle of Frame tests
    // ========================================================================

    #[test]
    fn test_time_to_frame_middle() {
        // At 25 fps, frame_duration = 40ms
        // Python's round() uses banker's rounding (round half to even)
        assert_eq!(time_to_frame_middle(0.0, FPS_25), 0); // 0.0/40 - 0.5 = -0.5, rounds to 0 (even)
        assert_eq!(time_to_frame_middle(20.0, FPS_25), 0); // 20.0/40 - 0.5 = 0.0, rounds to 0
        assert_eq!(time_to_frame_middle(60.0, FPS_25), 1); // 60.0/40 - 0.5 = 1.0, rounds to 1
    }

    #[test]
    fn test_frame_to_time_middle() {
        // At 23.976 fps, frame_duration = 41.708ms
        // Frame 24: (24 + 0.5) * 41.708 = 1022ms (rounded)
        let result = frame_to_time_middle(24, FPS_23976);
        assert!((result - 1022).abs() <= 1); // Allow ±1ms for rounding
    }

    // ========================================================================
    // MODE 2: Aegisub tests
    // ========================================================================

    #[test]
    fn test_time_to_frame_aegisub() {
        // Same as floor mode but without epsilon
        // At 23.976 fps, frame_duration = 41.70837504... ms
        assert_eq!(time_to_frame_aegisub(0.0, FPS_23976), 0);
        assert_eq!(time_to_frame_aegisub(41.707, FPS_23976), 0);
        assert_eq!(time_to_frame_aegisub(41.708, FPS_23976), 0); // Still in frame 0
        assert_eq!(time_to_frame_aegisub(41.709, FPS_23976), 1); // Frame 1 starts
    }

    #[test]
    fn test_frame_to_time_aegisub_centisecond_rounding() {
        // At 23.976 fps:
        // Frame 24 exact start: 24 * 41.708 = 1001.001ms
        // Ceil to centisecond: ceil(1001.001 / 10) * 10 = 1010ms
        let result = frame_to_time_aegisub(24, FPS_23976);
        assert_eq!(result, 1010);

        // Frame 0 should be 0ms (no rounding needed)
        assert_eq!(frame_to_time_aegisub(0, FPS_23976), 0);

        // Frame 1: 1 * 41.708 = 41.708ms → ceil(4.1708) * 10 = 50ms
        let result_f1 = frame_to_time_aegisub(1, FPS_23976);
        assert_eq!(result_f1, 50);
    }

    #[test]
    fn test_aegisub_ensures_within_frame() {
        // The Aegisub mode should ensure returned timestamp is within frame boundaries
        let frame = 24_i64;
        let time = frame_to_time_aegisub(frame, FPS_23976);

        // Verify that time falls within frame 24's display window
        let frame_back = time_to_frame_aegisub(time as f64, FPS_23976);
        assert_eq!(frame_back, frame, "Aegisub timestamp should fall within frame boundary");
    }

    // ========================================================================
    // Cross-mode consistency tests
    // ========================================================================

    #[test]
    fn test_all_modes_at_25fps() {
        // At 25 fps (PAL), frame_duration = 40ms exactly
        // This is a nice round number for testing

        // Frame 10 at 25fps
        let frame = 10_i64;

        // MODE 0: START
        let t_floor = frame_to_time_floor(frame, FPS_25);
        assert_eq!(t_floor, 400.0); // 10 * 40 = 400ms

        // MODE 1: MIDDLE
        let t_middle = frame_to_time_middle(frame, FPS_25);
        assert_eq!(t_middle, 420); // (10 + 0.5) * 40 = 420ms

        // MODE 2: AEGISUB
        let t_aegisub = frame_to_time_aegisub(frame, FPS_25);
        assert_eq!(t_aegisub, 400); // 10 * 40 = 400ms, already on centisecond
    }

    #[test]
    fn test_negative_frames() {
        // Pre-roll frames (negative frame numbers) should work
        let frame = -5_i64;

        let time = frame_to_time_floor(frame, FPS_25);
        assert_eq!(time, -200.0); // -5 * 40 = -200ms

        let back = time_to_frame_floor(time, FPS_25);
        assert_eq!(back, frame);
    }

    #[test]
    fn test_large_frame_numbers() {
        // Test with large frame numbers (feature-length film)
        // 2-hour film at 24fps = 172,800 frames
        let frame = 172800_i64;

        let time = frame_to_time_floor(frame, 24.0);
        assert!((time - 7_200_000.0).abs() < 1.0); // 2 hours = 7,200,000ms
    }

    #[test]
    fn test_various_framerates() {
        // Test common framerates
        let framerates = [23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0];

        for fps in framerates {
            // Basic sanity check: frame 0 should be at time 0
            assert_eq!(frame_to_time_floor(0, fps), 0.0);

            // Frame 1 should be at 1 frame duration
            let expected = 1000.0 / fps;
            let actual = frame_to_time_floor(1, fps);
            assert!((actual - expected).abs() < 0.001,
                "fps={}: expected {}, got {}", fps, expected, actual);
        }
    }
}
