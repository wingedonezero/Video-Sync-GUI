//! Audio track detection and selection.
//!
//! Uses mkvmerge to query track information from video files
//! and select audio tracks by language.

use std::path::Path;
use std::process::Command;

use serde::Deserialize;

use super::types::{AnalysisError, AnalysisResult};

/// Audio track information.
#[derive(Debug, Clone)]
pub struct AudioTrack {
    /// Track ID (mkvmerge track ID).
    pub id: i64,
    /// Audio stream index (0-based, for FFmpeg -map 0:a:N).
    pub stream_index: usize,
    /// Language code (e.g., "jpn", "eng").
    pub language: Option<String>,
    /// Track name/title.
    pub name: Option<String>,
    /// Codec ID.
    pub codec: Option<String>,
    /// Number of audio channels.
    pub channels: Option<u32>,
    /// Whether this is the default track.
    pub default: bool,
}

/// Result of mkvmerge -J command.
#[derive(Debug, Deserialize)]
struct MkvmergeInfo {
    tracks: Vec<MkvmergeTrack>,
}

#[derive(Debug, Deserialize)]
struct MkvmergeTrack {
    id: i64,
    #[serde(rename = "type")]
    track_type: String,
    properties: MkvmergeTrackProps,
}

#[derive(Debug, Deserialize)]
struct MkvmergeTrackProps {
    language: Option<String>,
    track_name: Option<String>,
    codec_id: Option<String>,
    audio_channels: Option<u32>,
    #[serde(default)]
    default_track: bool,
}

/// Get all audio tracks from a video file using mkvmerge.
pub fn get_audio_tracks(path: &Path) -> AnalysisResult<Vec<AudioTrack>> {
    if !path.exists() {
        return Err(AnalysisError::SourceNotFound(path.display().to_string()));
    }

    let output = Command::new("mkvmerge")
        .arg("-J")
        .arg(path)
        .output()
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to run mkvmerge: {}", e)))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(AnalysisError::FfmpegError(format!(
            "mkvmerge failed: {}",
            stderr
        )));
    }

    let json_str = String::from_utf8_lossy(&output.stdout);
    let info: MkvmergeInfo = serde_json::from_str(&json_str).map_err(|e| {
        AnalysisError::FfmpegError(format!("Failed to parse mkvmerge output: {}", e))
    })?;

    // Filter audio tracks and assign stream indices
    let mut audio_index = 0;
    let audio_tracks: Vec<AudioTrack> = info
        .tracks
        .into_iter()
        .filter(|t| t.track_type == "audio")
        .map(|t| {
            let track = AudioTrack {
                id: t.id,
                stream_index: audio_index,
                language: t.properties.language,
                name: t.properties.track_name,
                codec: t.properties.codec_id,
                channels: t.properties.audio_channels,
                default: t.properties.default_track,
            };
            audio_index += 1;
            track
        })
        .collect();

    Ok(audio_tracks)
}

/// Find an audio track by language code.
///
/// Returns the stream index (for FFmpeg -map 0:a:N) of the matching track.
/// If no match found, returns the first audio track's index (0).
/// If no audio tracks exist, returns None.
pub fn find_track_by_language(tracks: &[AudioTrack], language: Option<&str>) -> Option<usize> {
    if tracks.is_empty() {
        return None;
    }

    // If no language specified, return first track
    let lang = match language {
        Some(l) if !l.trim().is_empty() => l.trim().to_lowercase(),
        _ => return Some(0),
    };

    // Find matching track
    for track in tracks {
        if let Some(ref track_lang) = track.language {
            if track_lang.to_lowercase() == lang {
                tracing::debug!(
                    "Found track matching language '{}': stream index {}",
                    lang,
                    track.stream_index
                );
                return Some(track.stream_index);
            }
        }
    }

    // No match - fall back to first track
    tracing::debug!(
        "No track matching language '{}', using first track (index 0)",
        lang
    );
    Some(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn find_track_no_language_returns_first() {
        let tracks = vec![
            AudioTrack {
                id: 1,
                stream_index: 0,
                language: Some("eng".to_string()),
                name: None,
                codec: None,
                channels: Some(2),
                default: true,
            },
            AudioTrack {
                id: 2,
                stream_index: 1,
                language: Some("jpn".to_string()),
                name: None,
                codec: None,
                channels: Some(2),
                default: false,
            },
        ];

        assert_eq!(find_track_by_language(&tracks, None), Some(0));
        assert_eq!(find_track_by_language(&tracks, Some("")), Some(0));
    }

    #[test]
    fn find_track_by_language_matches() {
        let tracks = vec![
            AudioTrack {
                id: 1,
                stream_index: 0,
                language: Some("eng".to_string()),
                name: None,
                codec: None,
                channels: Some(2),
                default: true,
            },
            AudioTrack {
                id: 2,
                stream_index: 1,
                language: Some("jpn".to_string()),
                name: None,
                codec: None,
                channels: Some(2),
                default: false,
            },
        ];

        assert_eq!(find_track_by_language(&tracks, Some("jpn")), Some(1));
        assert_eq!(find_track_by_language(&tracks, Some("JPN")), Some(1)); // case insensitive
        assert_eq!(find_track_by_language(&tracks, Some("eng")), Some(0));
    }

    #[test]
    fn find_track_no_match_returns_first() {
        let tracks = vec![AudioTrack {
            id: 1,
            stream_index: 0,
            language: Some("eng".to_string()),
            name: None,
            codec: None,
            channels: Some(2),
            default: true,
        }];

        assert_eq!(find_track_by_language(&tracks, Some("fra")), Some(0));
    }

    #[test]
    fn find_track_empty_returns_none() {
        let tracks: Vec<AudioTrack> = vec![];
        assert_eq!(find_track_by_language(&tracks, Some("eng")), None);
    }
}
