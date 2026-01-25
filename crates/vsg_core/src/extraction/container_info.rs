//! Container information reading via mkvmerge.
//!
//! This module reads container delays (minimum_timestamp) from MKV files
//! which are essential for preserving A/V sync in Source 1.

use std::collections::HashMap;
use std::path::Path;
use std::process::Command;

use serde::Deserialize;

use super::types::{ContainerInfo, ExtractionError};

/// Parsed output from mkvmerge -J.
#[derive(Debug, Deserialize)]
struct MkvmergeJson {
    container: Option<MkvContainer>,
    tracks: Vec<MkvTrack>,
}

#[derive(Debug, Deserialize)]
struct MkvContainer {
    properties: Option<MkvContainerProps>,
}

#[derive(Debug, Deserialize)]
struct MkvContainerProps {
    duration: Option<i64>,
}

#[derive(Debug, Deserialize)]
struct MkvTrack {
    id: i64,
    #[serde(rename = "type")]
    track_type: String,
    properties: MkvTrackProps,
}

#[derive(Debug, Deserialize)]
struct MkvTrackProps {
    codec_id: Option<String>,
    /// Container delay in nanoseconds.
    /// This is the "minimum_timestamp" property.
    minimum_timestamp: Option<i64>,
}

/// Read container information from a media file.
///
/// Uses `mkvmerge -J` to extract track information including the
/// `minimum_timestamp` property which represents the container delay.
///
/// # Arguments
///
/// * `source_key` - The source identifier (e.g., "Source 1")
/// * `path` - Path to the media file
///
/// # Returns
///
/// `ContainerInfo` with track delays and video reference delay.
///
/// # Container Delay Explained
///
/// The container delay (`minimum_timestamp`) is the first presentation
/// timestamp of a track within the container. Tracks may not all start
/// at 0 - this is common in broadcast captures where audio may start
/// slightly before or after video.
///
/// For Source 1, we use the video track's container delay as the reference
/// and calculate relative delays for audio tracks to preserve sync.
pub fn read_container_info(
    source_key: &str,
    path: &Path,
) -> Result<ContainerInfo, ExtractionError> {
    // Verify file exists
    if !path.exists() {
        return Err(ExtractionError::FileNotFound(path.to_path_buf()));
    }

    // Run mkvmerge -J
    let output = Command::new("mkvmerge")
        .arg("-J")
        .arg(path)
        .output()
        .map_err(|e| ExtractionError::ToolExecutionFailed {
            tool: "mkvmerge".to_string(),
            message: format!("Failed to execute: {}", e),
        })?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(ExtractionError::ToolExecutionFailed {
            tool: "mkvmerge".to_string(),
            message: format!("Exit code {}: {}", output.status, stderr),
        });
    }

    // Parse JSON output
    let json_str = String::from_utf8_lossy(&output.stdout);
    let mkv_info: MkvmergeJson = serde_json::from_str(&json_str).map_err(|e| {
        ExtractionError::ParseError {
            tool: "mkvmerge".to_string(),
            message: format!("JSON parse error: {}", e),
        }
    })?;

    // Build container info
    let mut info = ContainerInfo::new(source_key, path.to_path_buf());

    // Extract duration
    info.duration_ms = mkv_info
        .container
        .and_then(|c| c.properties)
        .and_then(|p| p.duration)
        .map(|ns| ns / 1_000_000) // nanoseconds to milliseconds
        .unwrap_or(0);

    // Process each track
    for track in mkv_info.tracks {
        let track_id = track.id as usize;

        // Get container delay (minimum_timestamp) in milliseconds
        let delay_ms = track
            .properties
            .minimum_timestamp
            .map(|ns| ns / 1_000_000)
            .unwrap_or(0);

        info.track_delays_ms.insert(track_id, delay_ms);

        // Record first video track as reference
        if track.track_type == "video" && info.video_track_id.is_none() {
            info.video_track_id = Some(track_id);
            info.video_delay_ms = delay_ms;
        }
    }

    Ok(info)
}

/// Read container info for multiple sources.
///
/// Convenience function that reads container info for a map of sources.
pub fn read_all_container_info(
    sources: &HashMap<String, std::path::PathBuf>,
) -> Result<HashMap<String, ContainerInfo>, ExtractionError> {
    let mut results = HashMap::new();

    for (source_key, path) in sources {
        let info = read_container_info(source_key, path)?;
        results.insert(source_key.clone(), info);
    }

    Ok(results)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn test_nonexistent_file() {
        let result = read_container_info("Source 1", Path::new("/nonexistent/file.mkv"));
        assert!(matches!(result, Err(ExtractionError::FileNotFound(_))));
    }

    // Integration tests would require actual MKV files
    // Those should be in a separate integration test module
}
