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

    // Get container delay from minimum_timestamp (nanoseconds -> milliseconds)
    // Only video and audio tracks have meaningful container delays
    let container_delay_ms = match track_type {
        TrackType::Video | TrackType::Audio => properties
            .and_then(|p| p.get("minimum_timestamp"))
            .and_then(|m| m.as_i64())
            .map(|ns| (ns as f64 / 1_000_000.0).round() as i64)
            .unwrap_or(0),
        TrackType::Subtitles => 0, // Subtitles don't have meaningful container delays
    };

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
        container_delay_ms,
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
            props.width = p
                .get("pixel_dimensions")
                .and_then(|d| d.as_str())
                .and_then(|s| s.split('x').next())
                .and_then(|w| w.parse().ok());

            props.height = p
                .get("pixel_dimensions")
                .and_then(|d| d.as_str())
                .and_then(|s| s.split('x').nth(1))
                .and_then(|h| h.parse().ok());

            props.display_dimensions = p
                .get("display_dimensions")
                .and_then(|d| d.as_str())
                .map(|s| s.to_string())
                .or_else(|| {
                    p.get("pixel_dimensions")
                        .and_then(|d| d.as_str())
                        .map(|s| s.to_string())
                });

            // Calculate FPS from default_duration (nanoseconds per frame)
            props.fps = p
                .get("default_duration")
                .and_then(|d| d.as_u64())
                .map(|ns| 1_000_000_000.0 / ns as f64);
        }
        TrackType::Audio => {
            props.channels = p
                .get("audio_channels")
                .and_then(|c| c.as_u64())
                .map(|c| c as u8);

            props.sample_rate = p
                .get("audio_sampling_frequency")
                .and_then(|f| f.as_u64())
                .map(|f| f as u32);

            props.bits_per_sample = p
                .get("audio_bits_per_sample")
                .and_then(|b| b.as_u64())
                .map(|b| b as u8);
        }
        TrackType::Subtitles => {
            // Determine if text-based
            let codec_id = p.get("codec_id").and_then(|c| c.as_str()).unwrap_or("");

            props.text_subtitles =
                Some(codec_id.starts_with("S_TEXT/") || codec_id == "S_SSA" || codec_id == "S_ASS");
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

    let size = attachment.get("size").and_then(|s| s.as_u64()).unwrap_or(0);

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
    let count = probe
        .tracks
        .iter()
        .filter(|t| t.track_type == track_type)
        .count();
    Ok(count)
}

// =============================================================================
// FFPROBE DETAILED INFO
// =============================================================================

/// Detailed stream information from ffprobe.
///
/// This supplements mkvmerge info with additional details like bitrate,
/// profile, HDR metadata, etc.
#[derive(Debug, Clone, Default)]
pub struct FfprobeStreamInfo {
    /// Stream index (ffprobe ordering).
    pub index: usize,
    /// Codec type (video, audio, subtitle).
    pub codec_type: String,
    /// Codec name (e.g., "hevc", "aac").
    pub codec_name: String,
    /// Codec long name.
    pub codec_long_name: Option<String>,
    /// Codec profile (e.g., "Main 10", "LC").
    pub profile: Option<String>,
    /// Codec level.
    pub level: Option<i32>,
    /// Bit rate in bits/second.
    pub bit_rate: Option<u64>,
    /// Video width.
    pub width: Option<u32>,
    /// Video height.
    pub height: Option<u32>,
    /// Frame rate as string (e.g., "24000/1001").
    pub r_frame_rate: Option<String>,
    /// Color transfer function (for HDR detection).
    pub color_transfer: Option<String>,
    /// Color primaries.
    pub color_primaries: Option<String>,
    /// Has Dolby Vision.
    pub has_dolby_vision: bool,
    /// Sample rate for audio.
    pub sample_rate: Option<u32>,
    /// Number of audio channels.
    pub channels: Option<u8>,
    /// Channel layout string.
    pub channel_layout: Option<String>,
}

/// Get detailed stream information using ffprobe.
///
/// Returns a map of stream_index -> FfprobeStreamInfo.
pub fn get_detailed_stream_info(
    path: &Path,
) -> ExtractionResult<std::collections::HashMap<usize, FfprobeStreamInfo>> {
    if !path.exists() {
        return Err(ExtractionError::FileNotFound(path.to_path_buf()));
    }

    let output = Command::new("ffprobe")
        .args(["-v", "error", "-show_streams", "-of", "json"])
        .arg(path)
        .output()
        .map_err(|e| ExtractionError::ProbeFailed(format!("Failed to run ffprobe: {}", e)))?;

    if !output.status.success() {
        return Err(ExtractionError::CommandFailed {
            tool: "ffprobe".to_string(),
            exit_code: output.status.code().unwrap_or(-1),
            message: String::from_utf8_lossy(&output.stderr).to_string(),
        });
    }

    let json: Value = serde_json::from_slice(&output.stdout)?;
    let mut result = std::collections::HashMap::new();

    if let Some(streams) = json.get("streams").and_then(|s| s.as_array()) {
        for stream in streams {
            let index = stream.get("index").and_then(|i| i.as_u64()).unwrap_or(0) as usize;

            let mut info = FfprobeStreamInfo {
                index,
                codec_type: stream
                    .get("codec_type")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                codec_name: stream
                    .get("codec_name")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                codec_long_name: stream
                    .get("codec_long_name")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                profile: stream
                    .get("profile")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                level: stream
                    .get("level")
                    .and_then(|v| v.as_i64())
                    .map(|l| l as i32),
                bit_rate: stream
                    .get("bit_rate")
                    .and_then(|v| v.as_str())
                    .and_then(|s| s.parse().ok()),
                width: stream
                    .get("width")
                    .and_then(|v| v.as_u64())
                    .map(|w| w as u32),
                height: stream
                    .get("height")
                    .and_then(|v| v.as_u64())
                    .map(|h| h as u32),
                r_frame_rate: stream
                    .get("r_frame_rate")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                color_transfer: stream
                    .get("color_transfer")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                color_primaries: stream
                    .get("color_primaries")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
                has_dolby_vision: false,
                sample_rate: stream
                    .get("sample_rate")
                    .and_then(|v| v.as_str())
                    .and_then(|s| s.parse().ok()),
                channels: stream
                    .get("channels")
                    .and_then(|v| v.as_u64())
                    .map(|c| c as u8),
                channel_layout: stream
                    .get("channel_layout")
                    .and_then(|v| v.as_str())
                    .map(|s| s.to_string()),
            };

            // Check for Dolby Vision in side_data
            if let Some(side_data) = stream.get("side_data_list").and_then(|s| s.as_array()) {
                for sd in side_data {
                    if let Some(sd_type) = sd.get("side_data_type").and_then(|t| t.as_str()) {
                        if sd_type.contains("DOVI") || sd_type.contains("Dolby Vision") {
                            info.has_dolby_vision = true;
                        }
                    }
                }
            }

            result.insert(index, info);
        }
    }

    Ok(result)
}

// =============================================================================
// TRACK DESCRIPTION BUILDER
// =============================================================================

/// Codec ID to friendly name mapping.
const CODEC_ID_MAP: &[(&str, &str)] = &[
    // Video
    ("V_MPEGH/ISO/HEVC", "HEVC/H.265"),
    ("V_MPEG4/ISO/AVC", "AVC/H.264"),
    ("V_MPEG1", "MPEG-1"),
    ("V_MPEG2", "MPEG-2"),
    ("V_VP9", "VP9"),
    ("V_AV1", "AV1"),
    // Audio
    ("A_AC3", "AC-3"),
    ("A_EAC3", "E-AC3 / DD+"),
    ("A_DTS", "DTS"),
    ("A_TRUEHD", "TrueHD"),
    ("A_FLAC", "FLAC"),
    ("A_AAC", "AAC"),
    ("A_OPUS", "Opus"),
    ("A_VORBIS", "Vorbis"),
    ("A_PCM/INT/LIT", "PCM"),
    ("A_MS/ACM", "MS-ACM"),
    // Subtitles
    ("S_HDMV/PGS", "PGS"),
    ("S_TEXT/UTF8", "SRT"),
    ("S_TEXT/ASS", "ASS"),
    ("S_TEXT/SSA", "SSA"),
    ("S_VOBSUB", "VobSub"),
];

/// Get friendly codec name from codec ID.
pub fn friendly_codec_name(codec_id: &str) -> String {
    for (id, name) in CODEC_ID_MAP {
        if codec_id.starts_with(id) {
            return name.to_string();
        }
    }
    codec_id.to_string()
}

/// Get channel layout string from channel count.
pub fn channel_layout_str(channels: u8) -> &'static str {
    match channels {
        1 => "Mono",
        2 => "Stereo",
        6 => "5.1",
        8 => "7.1",
        _ => "",
    }
}

/// Build a rich, MediaInfo-like description for a track.
///
/// Combines mkvmerge track info with optional ffprobe details.
pub fn build_track_description(
    track: &TrackInfo,
    ffprobe_info: Option<&FfprobeStreamInfo>,
) -> String {
    let mut friendly_codec = friendly_codec_name(&track.codec_id);

    // Enhance codec name with profile info from ffprobe
    if let Some(fp) = ffprobe_info {
        if let Some(profile) = &fp.profile {
            if profile.contains("DTS-HD MA") {
                friendly_codec = "DTS-HD MA".to_string();
            } else if profile.contains("DTS-HD HRA") {
                friendly_codec = "DTS-HD HRA".to_string();
            }
        }
        if let Some(long_name) = &fp.codec_long_name {
            if long_name.contains("Atmos") {
                friendly_codec = "TrueHD / Atmos".to_string();
            }
        }
    }

    let lang = track.language.as_deref().unwrap_or("und");
    let name = track
        .name
        .as_ref()
        .map(|n| format!(" '{}'", n))
        .unwrap_or_default();

    let base_info = format!("{} ({}){}", friendly_codec, lang, name);
    let mut details = Vec::new();

    match track.track_type {
        TrackType::Video => {
            // Resolution
            if let Some(dims) = &track.properties.display_dimensions {
                details.push(dims.clone());
            } else if let (Some(w), Some(h)) = (track.properties.width, track.properties.height) {
                details.push(format!("{}x{}", w, h));
            }

            // FPS
            if let Some(fps) = track.properties.fps {
                details.push(format!("{:.3} fps", fps));
            } else if let Some(fp) = ffprobe_info {
                if let Some(rate) = &fp.r_frame_rate {
                    if let Some(fps) = parse_frame_rate(rate) {
                        details.push(format!("{:.3} fps", fps));
                    }
                }
            }

            // Bitrate
            if let Some(fp) = ffprobe_info {
                if let Some(br) = fp.bit_rate {
                    let mbps = br as f64 / 1_000_000.0;
                    details.push(format!("{:.1} Mb/s", mbps));
                }
            }

            // Profile + Level
            if let Some(fp) = ffprobe_info {
                if let Some(profile) = &fp.profile {
                    let mut profile_str = profile.clone();
                    if let Some(level) = fp.level {
                        let level_str = level.to_string();
                        if level_str.len() > 1 {
                            profile_str.push_str(&format!(
                                "@L{}.{}",
                                &level_str[..1],
                                &level_str[1..]
                            ));
                        } else {
                            profile_str.push_str(&format!("@L{}", level_str));
                        }
                    }
                    details.push(profile_str);
                }

                // HDR
                if let Some(ct) = &fp.color_transfer {
                    if ct == "smpte2084" {
                        details.push("HDR".to_string());
                    } else if ct == "arib-std-b67" {
                        details.push("HLG".to_string());
                    }
                }

                // Dolby Vision
                if fp.has_dolby_vision {
                    details.push("Dolby Vision".to_string());
                }
            }
        }
        TrackType::Audio => {
            // Bitrate - but skip for lossless codecs (TrueHD, FLAC, PCM)
            // as ffprobe reports misleading values (e.g., AC3 core bitrate for TrueHD)
            let is_lossless = track.codec_id.starts_with("A_TRUEHD")
                || track.codec_id.starts_with("A_FLAC")
                || track.codec_id.starts_with("A_PCM");

            if !is_lossless {
                if let Some(fp) = ffprobe_info {
                    if let Some(br) = fp.bit_rate {
                        let kbps = br / 1000;
                        details.push(format!("{} kb/s", kbps));
                    }
                }
            }

            // Sample rate
            if let Some(sr) = track.properties.sample_rate {
                details.push(format!("{} Hz", sr));
            }

            // Bit depth
            if let Some(bits) = track.properties.bits_per_sample {
                details.push(format!("{}-bit", bits));
            }

            // Channels
            if let Some(ch) = track.properties.channels {
                details.push(format!("{} ch", ch));
                let layout = channel_layout_str(ch);
                if !layout.is_empty() {
                    details.push(layout.to_string());
                }
            }
        }
        TrackType::Subtitles => {
            // No additional details for subtitles
        }
    }

    if details.is_empty() {
        base_info
    } else {
        format!("{} | {}", base_info, details.join(", "))
    }
}

/// Parse frame rate string like "24000/1001" into a float.
fn parse_frame_rate(rate: &str) -> Option<f64> {
    let parts: Vec<&str> = rate.split('/').collect();
    if parts.len() == 2 {
        let num: f64 = parts[0].parse().ok()?;
        let den: f64 = parts[1].parse().ok()?;
        if den != 0.0 {
            return Some(num / den);
        }
    }
    rate.parse().ok()
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
