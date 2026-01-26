//! File probing using mkvmerge -J.
//!
//! Provides functionality to probe Matroska and other container files
//! to get track, attachment, and metadata information.

use std::path::Path;
use std::process::Command;

use serde_json::Value;

use super::types::{
    AttachmentInfo, ExtractionError, ExtractionResult, ProbeResult, TrackInfo, TrackProperties,
    TrackType,
};

/// Probe a container file to get track and metadata information.
///
/// Uses mkvmerge -J to get detailed information about the file.
pub fn probe_file(path: &Path) -> ExtractionResult<ProbeResult> {
    if !path.exists() {
        return Err(ExtractionError::FileNotFound(path.to_path_buf()));
    }

    tracing::debug!("Probing file: {}", path.display());

    let output = Command::new("mkvmerge")
        .arg("-J")
        .arg(path)
        .output()
        .map_err(|e| ExtractionError::ProbeFailed(format!("Failed to run mkvmerge: {}", e)))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(ExtractionError::CommandFailed {
            tool: "mkvmerge".to_string(),
            exit_code: output.status.code().unwrap_or(-1),
            message: stderr.to_string(),
        });
    }

    let json: Value = serde_json::from_slice(&output.stdout)?;

    parse_probe_json(&json, path)
}

/// Parse the JSON output from mkvmerge -J.
fn parse_probe_json(json: &Value, path: &Path) -> ExtractionResult<ProbeResult> {
    let mut result = ProbeResult {
        file_path: path.to_path_buf(),
        ..Default::default()
    };

    // Container info
    if let Some(container) = json.get("container") {
        result.container = container
            .get("type")
            .and_then(|t| t.as_str())
            .unwrap_or("unknown")
            .to_string();

        // Duration from container properties
        if let Some(props) = container.get("properties") {
            if let Some(duration_ns) = props.get("duration").and_then(|d| d.as_u64()) {
                result.duration_ns = Some(duration_ns);
            }
        }
    }

    // Tracks
    if let Some(tracks) = json.get("tracks").and_then(|t| t.as_array()) {
        for track in tracks {
            if let Some(info) = parse_track_info(track) {
                result.tracks.push(info);
            }
        }
    }

    // Attachments
    if let Some(attachments) = json.get("attachments").and_then(|a| a.as_array()) {
        for attachment in attachments {
            if let Some(info) = parse_attachment_info(attachment) {
                result.attachments.push(info);
            }
        }
    }

    // Chapters
    if let Some(chapters) = json.get("chapters").and_then(|c| c.as_array()) {
        result.has_chapters = !chapters.is_empty();
    }

    Ok(result)
}

/// Parse a single track's information.
fn parse_track_info(track: &Value) -> Option<TrackInfo> {
    let track_type_str = track.get("type")?.as_str()?;
    let track_type = TrackType::from_str(track_type_str)?;

    let id = track.get("id")?.as_u64()? as usize;
    let codec_id = track
        .get("properties")
        .and_then(|p| p.get("codec_id"))
        .and_then(|c| c.as_str())
        .unwrap_or("")
        .to_string();

    let codec_name = track
        .get("codec")
        .and_then(|c| c.as_str())
        .unwrap_or(&codec_id)
        .to_string();

    let properties = track.get("properties");

    let language = properties
        .and_then(|p| p.get("language"))
        .and_then(|l| l.as_str())
        .map(|s| s.to_string());

    let name = properties
        .and_then(|p| p.get("track_name"))
        .and_then(|n| n.as_str())
        .map(|s| s.to_string());

    let is_default = properties
        .and_then(|p| p.get("default_track"))
        .and_then(|d| d.as_bool())
        .unwrap_or(false);

    let is_forced = properties
        .and_then(|p| p.get("forced_track"))
        .and_then(|f| f.as_bool())
        .unwrap_or(false);

    let is_enabled = properties
        .and_then(|p| p.get("enabled_track"))
        .and_then(|e| e.as_bool())
        .unwrap_or(true);

    let track_properties = parse_track_properties(track_type, properties);

    Some(TrackInfo {
        id,
        track_type,
        codec_id,
        codec_name,
        language,
        name,
        is_default,
        is_forced,
        is_enabled,
        properties: track_properties,
    })
}

/// Parse track-type-specific properties.
fn parse_track_properties(track_type: TrackType, properties: Option<&Value>) -> TrackProperties {
    let mut props = TrackProperties::default();

    let Some(p) = properties else {
        return props;
    };

    match track_type {
        TrackType::Video => {
            props.width = p.get("pixel_dimensions")
                .and_then(|d| d.as_str())
                .and_then(|s| s.split('x').next())
                .and_then(|w| w.parse().ok());

            props.height = p.get("pixel_dimensions")
                .and_then(|d| d.as_str())
                .and_then(|s| s.split('x').nth(1))
                .and_then(|h| h.parse().ok());

            props.display_dimensions = p.get("display_dimensions")
                .and_then(|d| d.as_str())
                .map(|s| s.to_string())
                .or_else(|| {
                    p.get("pixel_dimensions")
                        .and_then(|d| d.as_str())
                        .map(|s| s.to_string())
                });

            // Calculate FPS from default_duration (nanoseconds per frame)
            props.fps = p.get("default_duration")
                .and_then(|d| d.as_u64())
                .map(|ns| 1_000_000_000.0 / ns as f64);
        }
        TrackType::Audio => {
            props.channels = p.get("audio_channels")
                .and_then(|c| c.as_u64())
                .map(|c| c as u8);

            props.sample_rate = p.get("audio_sampling_frequency")
                .and_then(|f| f.as_u64())
                .map(|f| f as u32);

            props.bits_per_sample = p.get("audio_bits_per_sample")
                .and_then(|b| b.as_u64())
                .map(|b| b as u8);
        }
        TrackType::Subtitles => {
            // Determine if text-based
            let codec_id = p.get("codec_id")
                .and_then(|c| c.as_str())
                .unwrap_or("");

            props.text_subtitles = Some(
                codec_id.starts_with("S_TEXT/")
                    || codec_id == "S_SSA"
                    || codec_id == "S_ASS"
            );
        }
    }

    props
}

/// Parse attachment information.
fn parse_attachment_info(attachment: &Value) -> Option<AttachmentInfo> {
    let id = attachment.get("id")?.as_u64()? as usize;
    let name = attachment.get("file_name")?.as_str()?.to_string();

    let mime_type = attachment
        .get("content_type")
        .and_then(|c| c.as_str())
        .unwrap_or("application/octet-stream")
        .to_string();

    let size = attachment
        .get("size")
        .and_then(|s| s.as_u64())
        .unwrap_or(0);

    let description = attachment
        .get("description")
        .and_then(|d| d.as_str())
        .map(|s| s.to_string());

    Some(AttachmentInfo {
        id,
        name,
        mime_type,
        size,
        description,
    })
}

/// Quick check if a file is a valid Matroska container.
pub fn is_matroska(path: &Path) -> ExtractionResult<bool> {
    let probe = probe_file(path)?;
    Ok(probe.container.contains("Matroska"))
}

/// Get the duration of a file in seconds.
pub fn get_duration_secs(path: &Path) -> ExtractionResult<Option<f64>> {
    let probe = probe_file(path)?;
    Ok(probe.duration_secs())
}

/// Get just the track list without full probing.
pub fn get_tracks(path: &Path) -> ExtractionResult<Vec<TrackInfo>> {
    let probe = probe_file(path)?;
    Ok(probe.tracks)
}

/// Get just the attachment list.
pub fn get_attachments(path: &Path) -> ExtractionResult<Vec<AttachmentInfo>> {
    let probe = probe_file(path)?;
    Ok(probe.attachments)
}

/// Count tracks by type.
pub fn count_tracks_by_type(path: &Path, track_type: TrackType) -> ExtractionResult<usize> {
    let probe = probe_file(path)?;
    let count = probe.tracks.iter().filter(|t| t.track_type == track_type).count();
    Ok(count)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn probe_nonexistent_file() {
        let result = probe_file(&Path::new("/nonexistent/file.mkv"));
        assert!(matches!(result, Err(ExtractionError::FileNotFound(_))));
    }

    #[test]
    fn parse_track_type() {
        assert_eq!(TrackType::from_str("video"), Some(TrackType::Video));
        assert_eq!(TrackType::from_str("audio"), Some(TrackType::Audio));
        assert_eq!(TrackType::from_str("subtitles"), Some(TrackType::Subtitles));
        assert_eq!(TrackType::from_str("unknown"), None);
    }
}
