// vsg_core_rs/src/chapters/timestamps.rs
//
// Chapter timestamp manipulation (nanosecond precision).
//
// Provides functions for shifting chapter timestamps by a global offset.

/// Convert milliseconds to nanoseconds
///
/// CRITICAL: Chapter timestamps use nanosecond precision
///
/// # Arguments
/// * `ms` - Time in milliseconds
///
/// # Returns
/// Time in nanoseconds
///
/// # Examples
/// ```
/// assert_eq!(ms_to_ns(1), 1_000_000);
/// assert_eq!(ms_to_ns(1000), 1_000_000_000);
/// assert_eq!(ms_to_ns(-500), -500_000_000);
/// ```
pub fn ms_to_ns(ms: i64) -> i64 {
    ms * 1_000_000
}

/// Convert nanoseconds to milliseconds
///
/// # Arguments
/// * `ns` - Time in nanoseconds
///
/// # Returns
/// Time in milliseconds (rounded)
///
/// # Examples
/// ```
/// assert_eq!(ns_to_ms(1_000_000), 1);
/// assert_eq!(ns_to_ms(1_500_000), 2);  // Rounds up
/// assert_eq!(ns_to_ms(-1_500_000), -2);  // Rounds down
/// ```
pub fn ns_to_ms(ns: i64) -> i64 {
    (ns as f64 / 1_000_000.0).round() as i64
}

/// Shift a chapter timestamp by a given offset
///
/// CRITICAL PRESERVATION:
/// - Timestamps are in nanoseconds
/// - Shift is in milliseconds (converted to nanoseconds internally)
/// - Negative timestamps are clamped to 0 (chapters can't start before 0)
///
/// # Arguments
/// * `timestamp_ns` - Original timestamp in nanoseconds
/// * `shift_ms` - Shift amount in milliseconds (can be negative)
///
/// # Returns
/// Shifted timestamp in nanoseconds (clamped to >= 0)
///
/// # Examples
/// ```
/// assert_eq!(shift_timestamp_ns(1_000_000_000, 500), 1_500_000_000);
/// assert_eq!(shift_timestamp_ns(1_000_000_000, -500), 500_000_000);
/// assert_eq!(shift_timestamp_ns(100_000_000, -200), 0);  // Clamped to 0
/// ```
pub fn shift_timestamp_ns(timestamp_ns: i64, shift_ms: i64) -> i64 {
    let shift_ns = ms_to_ns(shift_ms);
    let new_timestamp = timestamp_ns + shift_ns;

    // CRITICAL: Clamp to 0 (chapters can't start before video start)
    new_timestamp.max(0)
}

/// Format nanoseconds as HH:MM:SS.nnnnnnnnn
///
/// Matches Python's _fmt_ns() function format for chapter timestamps.
///
/// # Arguments
/// * `ns` - Time in nanoseconds
///
/// # Returns
/// Formatted string: "HH:MM:SS.nnnnnnnnn"
///
/// # Examples
/// ```
/// assert_eq!(format_ns(0), "00:00:00.000000000");
/// assert_eq!(format_ns(1_000_000_000), "00:00:01.000000000");
/// assert_eq!(format_ns(3661_074_316_666), "01:01:01.074316666");
/// ```
pub fn format_ns(ns: i64) -> String {
    let ns = ns.max(0); // Clamp to non-negative
    let frac = ns % 1_000_000_000;
    let total_s = ns / 1_000_000_000;
    let hh = total_s / 3600;
    let mm = (total_s % 3600) / 60;
    let ss = total_s % 60;

    format!("{:02}:{:02}:{:02}.{:09}", hh, mm, ss, frac)
}

/// Parse timestamp string (HH:MM:SS.nnnnnnnnn) to nanoseconds
///
/// Matches Python's _parse_ns() function.
///
/// # Arguments
/// * `timestamp` - Timestamp string in format "HH:MM:SS.nnnnnnnnn"
///
/// # Returns
/// Time in nanoseconds
///
/// # Errors
/// Returns error if format is invalid
///
/// # Examples
/// ```
/// assert_eq!(parse_ns("00:00:00.000000000").unwrap(), 0);
/// assert_eq!(parse_ns("00:00:01.000000000").unwrap(), 1_000_000_000);
/// assert_eq!(parse_ns("01:01:01.074316666").unwrap(), 3661_074_316_666);
/// ```
pub fn parse_ns(timestamp: &str) -> Result<i64, String> {
    let parts: Vec<&str> = timestamp.trim().split(':').collect();
    if parts.len() != 3 {
        return Err(format!("Invalid timestamp format: {}", timestamp));
    }

    let hh: i64 = parts[0].parse()
        .map_err(|_| format!("Invalid hours: {}", parts[0]))?;
    let mm: i64 = parts[1].parse()
        .map_err(|_| format!("Invalid minutes: {}", parts[1]))?;

    let ss_parts: Vec<&str> = parts[2].split('.').collect();
    if ss_parts.len() != 2 {
        return Err(format!("Invalid seconds.fraction format: {}", parts[2]))?;
    }

    let ss: i64 = ss_parts[0].parse()
        .map_err(|_| format!("Invalid seconds: {}", ss_parts[0]))?;

    // Pad fraction to 9 digits (nanoseconds)
    let mut frac_str = ss_parts[1].to_string();
    while frac_str.len() < 9 {
        frac_str.push('0');
    }
    frac_str.truncate(9); // Ensure exactly 9 digits

    let frac: i64 = frac_str.parse()
        .map_err(|_| format!("Invalid fraction: {}", frac_str))?;

    let total_ns = (hh * 3600 + mm * 60 + ss) * 1_000_000_000 + frac;
    Ok(total_ns)
}

#[cfg(test)]
mod tests {
    use super::*;

    // ========================================================================
    // Conversion tests
    // ========================================================================

    #[test]
    fn test_ms_to_ns() {
        assert_eq!(ms_to_ns(0), 0);
        assert_eq!(ms_to_ns(1), 1_000_000);
        assert_eq!(ms_to_ns(1000), 1_000_000_000);
        assert_eq!(ms_to_ns(-500), -500_000_000);
    }

    #[test]
    fn test_ns_to_ms() {
        assert_eq!(ns_to_ms(0), 0);
        assert_eq!(ns_to_ms(1_000_000), 1);
        assert_eq!(ns_to_ms(1_500_000), 2);  // Rounds up
        assert_eq!(ns_to_ms(1_499_999), 1);  // Rounds down
        assert_eq!(ns_to_ms(-1_500_000), -2);  // Rounds down (negative)
    }

    // ========================================================================
    // Timestamp shifting tests
    // ========================================================================

    #[test]
    fn test_shift_timestamp_positive() {
        // Shift forward
        assert_eq!(shift_timestamp_ns(1_000_000_000, 500), 1_500_000_000);
        assert_eq!(shift_timestamp_ns(0, 1000), 1_000_000_000);
    }

    #[test]
    fn test_shift_timestamp_negative() {
        // Shift backward
        assert_eq!(shift_timestamp_ns(1_000_000_000, -500), 500_000_000);
        assert_eq!(shift_timestamp_ns(500_000_000, -400), 100_000_000);
    }

    #[test]
    fn test_shift_timestamp_clamp() {
        // CRITICAL: Clamp to 0 (chapters can't start before video start)
        assert_eq!(shift_timestamp_ns(100_000_000, -200), 0);
        assert_eq!(shift_timestamp_ns(0, -500), 0);
        assert_eq!(shift_timestamp_ns(1_000_000, -10), 0);
    }

    // ========================================================================
    // Format/parse tests
    // ========================================================================

    #[test]
    fn test_format_ns_zero() {
        assert_eq!(format_ns(0), "00:00:00.000000000");
    }

    #[test]
    fn test_format_ns_one_second() {
        assert_eq!(format_ns(1_000_000_000), "00:00:01.000000000");
    }

    #[test]
    fn test_format_ns_complex() {
        // 1 hour, 1 minute, 1 second, 74.316666 milliseconds
        let ns = 3661_074_316_666i64;
        assert_eq!(format_ns(ns), "01:01:01.074316666");
    }

    #[test]
    fn test_format_ns_negative_clamps() {
        // Negative values should be clamped to 0
        assert_eq!(format_ns(-1_000_000_000), "00:00:00.000000000");
    }

    #[test]
    fn test_parse_ns_zero() {
        assert_eq!(parse_ns("00:00:00.000000000").unwrap(), 0);
        assert_eq!(parse_ns("00:00:00.0").unwrap(), 0);  // Short fraction
    }

    #[test]
    fn test_parse_ns_one_second() {
        assert_eq!(parse_ns("00:00:01.000000000").unwrap(), 1_000_000_000);
        assert_eq!(parse_ns("00:00:01.0").unwrap(), 1_000_000_000);
    }

    #[test]
    fn test_parse_ns_complex() {
        let result = parse_ns("01:01:01.074316666").unwrap();
        assert_eq!(result, 3661_074_316_666);
    }

    #[test]
    fn test_parse_ns_short_fraction() {
        // Short fractions should be padded with zeros
        assert_eq!(parse_ns("00:00:00.123").unwrap(), 123_000_000);
        assert_eq!(parse_ns("00:00:00.1").unwrap(), 100_000_000);
    }

    #[test]
    fn test_parse_ns_long_fraction() {
        // Fractions longer than 9 digits should be truncated
        assert_eq!(parse_ns("00:00:00.1234567890123").unwrap(), 123_456_789);
    }

    #[test]
    fn test_format_parse_roundtrip() {
        let test_values = vec![
            0,
            1_000_000_000,
            3661_074_316_666,
            7200_000_000_000,  // 2 hours
        ];

        for ns in test_values {
            let formatted = format_ns(ns);
            let parsed = parse_ns(&formatted).unwrap();
            assert_eq!(parsed, ns, "Roundtrip failed for {}", ns);
        }
    }

    // ========================================================================
    // Integration tests
    // ========================================================================

    #[test]
    fn test_chapter_shift_workflow() {
        // Simulate shifting a chapter by +500ms
        let original_timestamp = "00:00:10.000000000";  // 10 seconds
        let shift_ms = 500;

        // Parse original
        let original_ns = parse_ns(original_timestamp).unwrap();
        assert_eq!(original_ns, 10_000_000_000);

        // Shift
        let shifted_ns = shift_timestamp_ns(original_ns, shift_ms);
        assert_eq!(shifted_ns, 10_500_000_000);

        // Format back
        let shifted_timestamp = format_ns(shifted_ns);
        assert_eq!(shifted_timestamp, "00:00:10.500000000");
    }

    #[test]
    fn test_chapter_shift_negative_workflow() {
        // Simulate shifting a chapter by -200ms
        let original_timestamp = "00:00:00.500000000";  // 0.5 seconds
        let shift_ms = -200;

        // Parse original
        let original_ns = parse_ns(original_timestamp).unwrap();
        assert_eq!(original_ns, 500_000_000);

        // Shift
        let shifted_ns = shift_timestamp_ns(original_ns, shift_ms);
        assert_eq!(shifted_ns, 300_000_000);

        // Format back
        let shifted_timestamp = format_ns(shifted_ns);
        assert_eq!(shifted_timestamp, "00:00:00.300000000");
    }

    #[test]
    fn test_chapter_shift_clamp_workflow() {
        // Simulate shifting a chapter that would go negative
        let original_timestamp = "00:00:00.100000000";  // 0.1 seconds
        let shift_ms = -200;  // Shift by -200ms

        // Parse original
        let original_ns = parse_ns(original_timestamp).unwrap();

        // Shift (should clamp to 0)
        let shifted_ns = shift_timestamp_ns(original_ns, shift_ms);
        assert_eq!(shifted_ns, 0);

        // Format back
        let shifted_timestamp = format_ns(shifted_ns);
        assert_eq!(shifted_timestamp, "00:00:00.000000000");
    }
}
