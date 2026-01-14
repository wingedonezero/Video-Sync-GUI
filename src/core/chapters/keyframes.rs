//! Keyframe detection for chapter snapping

use crate::core::io::runner::CommandRunner;
use crate::core::models::results::CoreResult;
use serde_json::Value;
use std::path::Path;

/// Probe keyframe timestamps from a video file
///
/// Uses ffprobe to extract packet information and filters for keyframes (K flag).
/// Returns a sorted vector of keyframe timestamps in nanoseconds.
pub fn probe_keyframes_ns(
    video_path: &Path,
    runner: &CommandRunner,
) -> CoreResult<Vec<i64>> {
    let cmd = vec![
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "packet=pts_time,flags",
        "-of",
        "json",
        video_path.to_str().unwrap(),
    ];

    let output = runner.run(&cmd)?.stdout;

    // Parse JSON response
    let json: Value = serde_json::from_str(&output)
        .map_err(|e| format!("Failed to parse ffprobe JSON: {}", e))?;

    let mut keyframes_ns = Vec::new();

    if let Some(packets) = json["packets"].as_array() {
        for packet in packets {
            // Check if this packet is a keyframe (contains 'K' in flags)
            if let Some(flags) = packet["flags"].as_str() {
                if flags.contains('K') {
                    // Extract pts_time and convert to nanoseconds
                    if let Some(pts_time_str) = packet["pts_time"].as_str() {
                        if let Ok(pts_time_sec) = pts_time_str.parse::<f64>() {
                            let pts_ns = (pts_time_sec * 1_000_000_000.0).round() as i64;
                            keyframes_ns.push(pts_ns);
                        }
                    }
                }
            }
        }
    }

    // Sort keyframes
    keyframes_ns.sort_unstable();

    Ok(keyframes_ns)
}
