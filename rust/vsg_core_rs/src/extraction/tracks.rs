// vsg_core_rs/src/extraction/tracks.rs
//
// Track extraction and container delay calculation.
//
// Parses mkvmerge -J JSON output and calculates container delays from
// minimum_timestamp values (nanoseconds → milliseconds).

use serde::{Deserialize, Serialize};
use serde_json::Value;

/// Calculate container delay in milliseconds from minimum_timestamp (nanoseconds)
///
/// CRITICAL PRESERVATION:
/// - minimum_timestamp is in NANOSECONDS (from mkvmerge -J output)
/// - Use round() not int() for proper rounding of negative values
/// - int() truncates toward zero: int(-1001.825) = -1001 (WRONG)
/// - round() rounds to nearest: round(-1001.825) = -1002 (CORRECT)
///
/// # Arguments
/// * `minimum_timestamp_ns` - Timestamp in nanoseconds from mkvmerge -J
///
/// # Returns
/// Container delay in milliseconds (rounded to nearest integer)
///
/// # Examples
/// ```
/// assert_eq!(calculate_container_delay(1_000_000), 1);     // 1ms
/// assert_eq!(calculate_container_delay(1_500_000), 2);     // 1.5ms → rounds to 2ms
/// assert_eq!(calculate_container_delay(-1_500_000), -2);   // -1.5ms → rounds to -2ms
/// assert_eq!(calculate_container_delay(0), 0);
/// ```
pub fn calculate_container_delay(minimum_timestamp_ns: i64) -> i32 {
    // Convert nanoseconds to milliseconds and round to nearest integer
    // CRITICAL: Use round() not truncate for correct negative value handling
    (minimum_timestamp_ns as f64 / 1_000_000.0).round() as i32
}

/// Process mkvmerge -J JSON output to add container_delay_ms to tracks
///
/// CRITICAL RULES:
/// - ONLY audio and video tracks get container delays calculated
/// - Subtitles ALWAYS get container_delay_ms = 0
/// - Container delay is calculated from properties.minimum_timestamp (nanoseconds)
/// - Formula: round(minimum_timestamp / 1_000_000)
///
/// # Arguments
/// * `json_str` - JSON string from `mkvmerge -J <file>` command
///
/// # Returns
/// Modified JSON with container_delay_ms added to each track
///
/// # Errors
/// Returns error if JSON is invalid
pub fn add_container_delays_to_json(json_str: &str) -> Result<String, String> {
    // Parse mkvmerge JSON output
    let mut info: Value = serde_json::from_str(json_str)
        .map_err(|e| format!("Failed to parse mkvmerge JSON: {}", e))?;

    // Process each track
    if let Some(tracks) = info.get_mut("tracks").and_then(|t| t.as_array_mut()) {
        for track in tracks {
            let track_type = track.get("type")
                .and_then(|t| t.as_str())
                .unwrap_or("");

            // ONLY read container delays for audio and video tracks
            // Subtitles don't have meaningful container delays in MKV
            let container_delay_ms = if track_type == "audio" || track_type == "video" {
                let minimum_timestamp = track.get("properties")
                    .and_then(|p| p.get("minimum_timestamp"))
                    .and_then(|t| t.as_i64())
                    .unwrap_or(0);

                if minimum_timestamp != 0 {
                    calculate_container_delay(minimum_timestamp)
                } else {
                    0
                }
            } else {
                // Explicitly set subtitle delays to 0
                0
            };

            // Add container_delay_ms to track
            track.as_object_mut()
                .unwrap()
                .insert("container_delay_ms".to_string(), Value::from(container_delay_ms));
        }
    }

    // Serialize back to JSON
    serde_json::to_string(&info)
        .map_err(|e| format!("Failed to serialize JSON: {}", e))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_calculate_container_delay_positive() {
        // Positive values
        assert_eq!(calculate_container_delay(0), 0);
        assert_eq!(calculate_container_delay(1_000_000), 1);  // 1ms
        assert_eq!(calculate_container_delay(1_500_000), 2);  // 1.5ms → rounds up
        assert_eq!(calculate_container_delay(1_499_999), 1);  // 1.499999ms → rounds down
        assert_eq!(calculate_container_delay(1_000_000_000), 1000);  // 1 second
    }

    #[test]
    fn test_calculate_container_delay_negative() {
        // CRITICAL: Negative values must use round() not int()
        assert_eq!(calculate_container_delay(-1_000_000), -1);  // -1ms
        assert_eq!(calculate_container_delay(-1_500_000), -2);  // -1.5ms → rounds to -2 (not -1!)
        assert_eq!(calculate_container_delay(-1_499_999), -1);  // -1.499999ms → rounds to -1
        assert_eq!(calculate_container_delay(-1_001_825_000), -1002);  // Example from code comment
    }

    #[test]
    fn test_calculate_container_delay_edge_cases() {
        // Edge cases
        assert_eq!(calculate_container_delay(500_000), 1);    // 0.5ms → rounds up
        assert_eq!(calculate_container_delay(-500_000), -1);   // -0.5ms → rounds down (to -1)
        assert_eq!(calculate_container_delay(499_999), 0);    // Just under 0.5ms → rounds down
        assert_eq!(calculate_container_delay(-499_999), 0);   // Just under -0.5ms → rounds up (to 0)
    }

    #[test]
    fn test_add_container_delays_audio_video() {
        let json = r#"{
            "tracks": [
                {
                    "type": "video",
                    "id": 0,
                    "properties": {
                        "minimum_timestamp": 1001001000
                    }
                },
                {
                    "type": "audio",
                    "id": 1,
                    "properties": {
                        "minimum_timestamp": 1500000000
                    }
                },
                {
                    "type": "subtitles",
                    "id": 2,
                    "properties": {
                        "minimum_timestamp": 999999999
                    }
                }
            ]
        }"#;

        let result = add_container_delays_to_json(json).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        let tracks = parsed["tracks"].as_array().unwrap();

        // Video track: 1001001000ns / 1000000 = 1001.001ms → rounds to 1001ms
        assert_eq!(tracks[0]["container_delay_ms"].as_i64().unwrap(), 1001);

        // Audio track: 1500000000ns / 1000000 = 1500ms
        assert_eq!(tracks[1]["container_delay_ms"].as_i64().unwrap(), 1500);

        // Subtitle track: ALWAYS 0 regardless of minimum_timestamp
        assert_eq!(tracks[2]["container_delay_ms"].as_i64().unwrap(), 0);
    }

    #[test]
    fn test_add_container_delays_zero_values() {
        let json = r#"{
            "tracks": [
                {
                    "type": "audio",
                    "id": 0,
                    "properties": {}
                },
                {
                    "type": "video",
                    "id": 1,
                    "properties": {
                        "minimum_timestamp": 0
                    }
                }
            ]
        }"#;

        let result = add_container_delays_to_json(json).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        let tracks = parsed["tracks"].as_array().unwrap();

        // Missing minimum_timestamp → defaults to 0
        assert_eq!(tracks[0]["container_delay_ms"].as_i64().unwrap(), 0);

        // Explicit minimum_timestamp = 0 → delay = 0
        assert_eq!(tracks[1]["container_delay_ms"].as_i64().unwrap(), 0);
    }

    #[test]
    fn test_add_container_delays_negative() {
        let json = r#"{
            "tracks": [
                {
                    "type": "audio",
                    "id": 0,
                    "properties": {
                        "minimum_timestamp": -1001825000
                    }
                }
            ]
        }"#;

        let result = add_container_delays_to_json(json).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        let tracks = parsed["tracks"].as_array().unwrap();

        // -1001825000ns / 1000000 = -1001.825ms → rounds to -1002ms (not -1001!)
        assert_eq!(tracks[0]["container_delay_ms"].as_i64().unwrap(), -1002);
    }

    #[test]
    fn test_add_container_delays_preserves_other_fields() {
        let json = r#"{
            "container": {
                "properties": {
                    "duration": 120000000000
                }
            },
            "tracks": [
                {
                    "type": "video",
                    "id": 0,
                    "codec": "V_MPEG4/ISO/AVC",
                    "properties": {
                        "codec_id": "V_MPEG4/ISO/AVC",
                        "minimum_timestamp": 1000000
                    }
                }
            ]
        }"#;

        let result = add_container_delays_to_json(json).unwrap();
        let parsed: Value = serde_json::from_str(&result).unwrap();

        // Container info should be preserved
        assert_eq!(parsed["container"]["properties"]["duration"].as_i64().unwrap(), 120000000000);

        // Track fields should be preserved
        let track = &parsed["tracks"][0];
        assert_eq!(track["codec"].as_str().unwrap(), "V_MPEG4/ISO/AVC");
        assert_eq!(track["properties"]["codec_id"].as_str().unwrap(), "V_MPEG4/ISO/AVC");

        // container_delay_ms should be added
        assert_eq!(track["container_delay_ms"].as_i64().unwrap(), 1);
    }
}
