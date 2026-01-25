//! Track extraction via mkvextract.
//!
//! This module handles extracting individual tracks from MKV files
//! for processing (e.g., audio correction, subtitle manipulation).

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::process::Command;

use crate::models::TrackType;

use super::types::{ExtractRequest, ExtractedTrack, ExtractionError};

/// Map codec IDs to file extensions.
///
/// This is used to determine the appropriate file extension when
/// extracting tracks from MKV containers.
fn codec_to_extension(codec_id: &str, track_type: TrackType) -> &'static str {
    match track_type {
        TrackType::Video => match codec_id {
            c if c.contains("AVC") || c.contains("H264") => "h264",
            c if c.contains("HEVC") || c.contains("H265") => "hevc",
            c if c.contains("VP9") => "ivf",
            c if c.contains("VP8") => "ivf",
            c if c.contains("AV1") => "ivf",
            c if c.contains("MPEG4") => "m4v",
            _ => "mkv", // Fallback to container
        },
        TrackType::Audio => match codec_id {
            c if c.contains("AAC") => "aac",
            c if c.contains("AC3") || c.contains("AC-3") => "ac3",
            c if c.contains("EAC3") || c.contains("E-AC-3") => "eac3",
            c if c.contains("DTS") => "dts",
            c if c.contains("FLAC") => "flac",
            c if c.contains("OPUS") => "opus",
            c if c.contains("VORBIS") => "ogg",
            c if c.contains("TRUEHD") => "thd",
            c if c.contains("MP3") => "mp3",
            c if c.contains("PCM") => "wav",
            c if c.contains("MS/ACM") => "wav", // Needs special handling
            _ => "mka", // Fallback to Matroska audio
        },
        TrackType::Subtitles => match codec_id {
            c if c.contains("ASS") || c.contains("SSA") => "ass",
            c if c.contains("SRT") || c.contains("UTF8") => "srt",
            c if c.contains("WEBVTT") => "vtt",
            c if c.contains("PGS") || c.contains("HDMV") => "sup",
            c if c.contains("VOBSUB") || c.contains("DVD") => "sub",
            _ => "mks", // Fallback to Matroska subtitles
        },
    }
}

/// Check if a codec requires special extraction handling.
///
/// Some codecs (like A_MS/ACM) can't be directly extracted and need
/// conversion via FFmpeg instead.
fn needs_ffmpeg_extraction(codec_id: &str) -> bool {
    codec_id.contains("MS/ACM")
}

/// Generate output filename for an extracted track.
fn generate_output_filename(
    source_key: &str,
    track_id: usize,
    extension: &str,
) -> String {
    // Sanitize source key for filename
    let safe_key = source_key.replace(' ', "_").to_lowercase();
    format!("{}_{}.{}", safe_key, track_id, extension)
}

/// Extract a single track using mkvextract.
fn extract_track_mkvextract(
    source_path: &Path,
    track_id: usize,
    output_path: &Path,
) -> Result<(), ExtractionError> {
    let track_spec = format!("{}:{}", track_id, output_path.display());

    let output = Command::new("mkvextract")
        .arg("tracks")
        .arg(source_path)
        .arg(&track_spec)
        .output()
        .map_err(|e| ExtractionError::ToolExecutionFailed {
            tool: "mkvextract".to_string(),
            message: format!("Failed to execute: {}", e),
        })?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(ExtractionError::TrackExtractionFailed {
            track_id,
            message: format!("mkvextract failed: {}", stderr),
        });
    }

    // Verify output exists and isn't empty
    if !output_path.exists() {
        return Err(ExtractionError::OutputMissing(output_path.to_path_buf()));
    }

    let metadata = std::fs::metadata(output_path).map_err(|e| {
        ExtractionError::IoError(format!("Failed to read output metadata: {}", e))
    })?;

    if metadata.len() == 0 {
        return Err(ExtractionError::OutputMissing(output_path.to_path_buf()));
    }

    Ok(())
}

/// Extract a track that requires FFmpeg conversion (e.g., A_MS/ACM).
fn extract_track_ffmpeg(
    source_path: &Path,
    track_id: usize,
    output_path: &Path,
) -> Result<(), ExtractionError> {
    // FFmpeg uses 0-based stream index, mkvmerge uses track ID
    // For audio, we need to find the correct stream index
    // For simplicity, we'll extract to WAV format

    let output = Command::new("ffmpeg")
        .arg("-y")
        .arg("-i")
        .arg(source_path)
        .arg("-map")
        .arg(format!("0:{}", track_id))
        .arg("-c:a")
        .arg("pcm_s16le")
        .arg(output_path)
        .output()
        .map_err(|e| ExtractionError::ToolExecutionFailed {
            tool: "ffmpeg".to_string(),
            message: format!("Failed to execute: {}", e),
        })?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(ExtractionError::TrackExtractionFailed {
            track_id,
            message: format!("ffmpeg extraction failed: {}", stderr),
        });
    }

    // Verify output exists
    if !output_path.exists() || output_path.metadata().map(|m| m.len()).unwrap_or(0) == 0 {
        return Err(ExtractionError::OutputMissing(output_path.to_path_buf()));
    }

    Ok(())
}

/// Extract multiple tracks from source files.
///
/// # Arguments
///
/// * `requests` - List of tracks to extract
///
/// # Returns
///
/// Map of successfully extracted tracks, keyed by "{source_key}:{track_id}".
///
/// # Errors
///
/// Returns an error if any critical extraction fails. Non-critical failures
/// are logged but don't stop the process.
pub fn extract_tracks(
    requests: &[ExtractRequest],
) -> Result<HashMap<String, ExtractedTrack>, ExtractionError> {
    let mut results = HashMap::new();

    for request in requests {
        // Determine file extension
        let extension = codec_to_extension(&request.codec_id, request.track_type);

        // Generate output path
        let filename = generate_output_filename(
            &request.source_key,
            request.track_id,
            extension,
        );
        let output_path = request.output_dir.join(&filename);

        // Create output directory if needed
        if let Some(parent) = output_path.parent() {
            std::fs::create_dir_all(parent).map_err(|e| {
                ExtractionError::IoError(format!(
                    "Failed to create output directory: {}",
                    e
                ))
            })?;
        }

        // Extract based on codec type
        let result = if needs_ffmpeg_extraction(&request.codec_id) {
            extract_track_ffmpeg(&request.source_path, request.track_id, &output_path)
        } else {
            extract_track_mkvextract(&request.source_path, request.track_id, &output_path)
        };

        match result {
            Ok(()) => {
                let key = format!("{}:{}", request.source_key, request.track_id);
                results.insert(
                    key,
                    ExtractedTrack {
                        source_key: request.source_key.clone(),
                        track_id: request.track_id,
                        track_type: request.track_type,
                        codec_id: request.codec_id.clone(),
                        extracted_path: output_path,
                        extension: extension.to_string(),
                    },
                );
            }
            Err(e) => {
                // Log error but continue with other tracks
                tracing::warn!(
                    "Failed to extract track {} from {}: {}",
                    request.track_id,
                    request.source_path.display(),
                    e
                );
                // For critical tracks, we might want to return early
                // For now, we continue and let the caller handle missing tracks
            }
        }
    }

    Ok(results)
}

/// Extract a single track (convenience function).
pub fn extract_single_track(
    source_key: &str,
    source_path: &Path,
    track_id: usize,
    track_type: TrackType,
    codec_id: &str,
    output_dir: &Path,
) -> Result<ExtractedTrack, ExtractionError> {
    let request = ExtractRequest {
        source_key: source_key.to_string(),
        source_path: source_path.to_path_buf(),
        track_id,
        track_type,
        codec_id: codec_id.to_string(),
        output_dir: output_dir.to_path_buf(),
    };

    let mut results = extract_tracks(&[request])?;
    let key = format!("{}:{}", source_key, track_id);

    results.remove(&key).ok_or(ExtractionError::TrackExtractionFailed {
        track_id,
        message: "Track extraction produced no output".to_string(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_codec_to_extension() {
        assert_eq!(codec_to_extension("A_FLAC", TrackType::Audio), "flac");
        assert_eq!(codec_to_extension("A_AAC", TrackType::Audio), "aac");
        assert_eq!(codec_to_extension("A_AC3", TrackType::Audio), "ac3");
        assert_eq!(codec_to_extension("A_DTS", TrackType::Audio), "dts");
        assert_eq!(codec_to_extension("S_TEXT/ASS", TrackType::Subtitles), "ass");
        assert_eq!(codec_to_extension("S_TEXT/UTF8", TrackType::Subtitles), "srt");
        assert_eq!(codec_to_extension("V_MPEGH/ISO/HEVC", TrackType::Video), "hevc");
    }

    #[test]
    fn test_needs_ffmpeg_extraction() {
        assert!(needs_ffmpeg_extraction("A_MS/ACM"));
        assert!(!needs_ffmpeg_extraction("A_FLAC"));
        assert!(!needs_ffmpeg_extraction("A_AAC"));
    }

    #[test]
    fn test_generate_output_filename() {
        assert_eq!(
            generate_output_filename("Source 1", 2, "flac"),
            "source_1_2.flac"
        );
        assert_eq!(
            generate_output_filename("Source 2", 0, "ass"),
            "source_2_0.ass"
        );
    }
}
