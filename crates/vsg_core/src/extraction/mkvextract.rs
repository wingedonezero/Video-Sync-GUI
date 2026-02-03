//! Low-level mkvextract command wrapper.
//!
//! Provides a safe interface to the mkvextract tool for extracting
//! tracks, attachments, chapters, and other data from Matroska files.

use std::path::Path;
use std::process::Command;

use super::types::{ExtractionError, ExtractionResult};

/// Run mkvextract with the given mode and arguments.
///
/// This is the low-level wrapper that handles command execution
/// and error handling.
fn run_mkvextract(
    input_path: &Path,
    mode: &str,
    args: &[&str],
) -> ExtractionResult<std::process::Output> {
    if !input_path.exists() {
        return Err(ExtractionError::FileNotFound(input_path.to_path_buf()));
    }

    let mut cmd = Command::new("mkvextract");
    cmd.arg(input_path).arg(mode);

    for arg in args {
        cmd.arg(arg);
    }

    tracing::debug!(
        "Running: mkvextract {} {} {}",
        input_path.display(),
        mode,
        args.join(" ")
    );

    let output = cmd.output().map_err(|e| {
        ExtractionError::ExtractionFailed(format!("Failed to run mkvextract: {}", e))
    })?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(ExtractionError::CommandFailed {
            tool: "mkvextract".to_string(),
            exit_code: output.status.code().unwrap_or(-1),
            message: stderr.to_string(),
        });
    }

    Ok(output)
}

/// Extract a single track from an MKV file.
///
/// # Arguments
/// * `input_path` - Path to the source MKV file
/// * `track_id` - Track ID to extract
/// * `output_path` - Path where the track will be written
///
/// # Returns
/// `Ok(())` on success, `Err` on failure
pub fn extract_track(
    input_path: &Path,
    track_id: usize,
    output_path: &Path,
) -> ExtractionResult<()> {
    let track_spec = format!("{}:{}", track_id, output_path.display());

    run_mkvextract(input_path, "tracks", &[&track_spec])?;

    tracing::info!(
        "Extracted track {} from {} to {}",
        track_id,
        input_path.display(),
        output_path.display()
    );

    Ok(())
}

/// Extract multiple tracks from an MKV file in one pass.
///
/// # Arguments
/// * `input_path` - Path to the source MKV file
/// * `track_specs` - List of (track_id, output_path) tuples
///
/// More efficient than multiple single-track extractions.
pub fn extract_tracks(input_path: &Path, track_specs: &[(usize, &Path)]) -> ExtractionResult<()> {
    if track_specs.is_empty() {
        return Ok(());
    }

    let specs: Vec<String> = track_specs
        .iter()
        .map(|(id, path)| format!("{}:{}", id, path.display()))
        .collect();

    let spec_refs: Vec<&str> = specs.iter().map(|s| s.as_str()).collect();

    run_mkvextract(input_path, "tracks", &spec_refs)?;

    tracing::info!(
        "Extracted {} tracks from {}",
        track_specs.len(),
        input_path.display()
    );

    Ok(())
}

/// Extract attachments from an MKV file.
///
/// # Arguments
/// * `input_path` - Path to the source MKV file
/// * `attachment_specs` - List of (attachment_id, output_path) tuples
///
/// If `attachment_specs` is empty, no attachments are extracted.
pub fn extract_attachments(
    input_path: &Path,
    attachment_specs: &[(usize, &Path)],
) -> ExtractionResult<()> {
    if attachment_specs.is_empty() {
        return Ok(());
    }

    let specs: Vec<String> = attachment_specs
        .iter()
        .map(|(id, path)| format!("{}:{}", id, path.display()))
        .collect();

    let spec_refs: Vec<&str> = specs.iter().map(|s| s.as_str()).collect();

    run_mkvextract(input_path, "attachments", &spec_refs)?;

    tracing::info!(
        "Extracted {} attachments from {}",
        attachment_specs.len(),
        input_path.display()
    );

    Ok(())
}

/// Extract chapters from an MKV file to XML.
///
/// Returns the chapter XML content as a string.
pub fn extract_chapters_xml(input_path: &Path) -> ExtractionResult<Option<String>> {
    let output = run_mkvextract(input_path, "chapters", &["--output-charset", "UTF-8"])?;

    let xml = String::from_utf8_lossy(&output.stdout).to_string();
    if xml.trim().is_empty() {
        return Ok(None);
    }

    Ok(Some(xml))
}

/// Extract timestamps from an MKV file.
///
/// Extracts the timestamps for a specific track to the v2 format.
pub fn extract_timestamps(
    input_path: &Path,
    track_id: usize,
    output_path: &Path,
) -> ExtractionResult<()> {
    let track_spec = format!("{}:{}", track_id, output_path.display());

    run_mkvextract(input_path, "timestamps_v2", &[&track_spec])?;

    tracing::info!(
        "Extracted timestamps for track {} to {}",
        track_id,
        output_path.display()
    );

    Ok(())
}

/// Extract cue data from an MKV file.
///
/// Extracts the cue (index) data for a specific track.
pub fn extract_cues(
    input_path: &Path,
    track_id: usize,
    output_path: &Path,
) -> ExtractionResult<()> {
    let track_spec = format!("{}:{}", track_id, output_path.display());

    run_mkvextract(input_path, "cues", &[&track_spec])?;

    tracing::info!(
        "Extracted cues for track {} to {}",
        track_id,
        output_path.display()
    );

    Ok(())
}

/// Extract tags from an MKV file to XML.
pub fn extract_tags(input_path: &Path, output_path: &Path) -> ExtractionResult<()> {
    let output_str = output_path.display().to_string();

    run_mkvextract(input_path, "tags", &[&output_str])?;

    tracing::info!("Extracted tags to {}", output_path.display());

    Ok(())
}

/// Get the appropriate file extension for a track codec.
///
/// This helps determine the output filename for extracted tracks.
pub fn extension_for_codec(codec_id: &str) -> &'static str {
    match codec_id {
        // Video codecs
        "V_MPEG4/ISO/AVC" | "V_MS/VFW/FOURCC" => "h264",
        "V_MPEGH/ISO/HEVC" => "h265",
        "V_VP8" => "ivf",
        "V_VP9" => "ivf",
        "V_AV1" => "obu",
        "V_MPEG1" | "V_MPEG2" => "mpg",

        // Audio codecs
        "A_AAC" | "A_AAC/MPEG2/LC" | "A_AAC/MPEG4/LC" | "A_AAC/MPEG4/LC/SBR" => "aac",
        "A_AC3" | "A_EAC3" => "ac3",
        "A_DTS" => "dts",
        "A_FLAC" => "flac",
        "A_OPUS" => "opus",
        "A_VORBIS" => "ogg",
        "A_PCM/INT/LIT" | "A_PCM/INT/BIG" => "wav",
        "A_MPEG/L3" => "mp3",
        "A_MPEG/L2" => "mp2",
        "A_TRUEHD" => "thd",
        "A_MS/ACM" => "wav", // ACM needs ffmpeg extraction

        // Subtitle codecs
        "S_TEXT/UTF8" | "S_TEXT/ASCII" => "srt",
        "S_TEXT/SSA" | "S_TEXT/ASS" => "ass",
        "S_TEXT/WEBVTT" => "vtt",
        "S_VOBSUB" => "sub",
        "S_HDMV/PGS" => "sup",

        // Default
        _ => "bin",
    }
}

/// Check if a codec requires ffmpeg for extraction.
///
/// Some codecs (like A_MS/ACM) cannot be extracted directly by mkvextract
/// and need ffmpeg as a fallback.
pub fn requires_ffmpeg_extraction(codec_id: &str) -> bool {
    codec_id.to_uppercase().contains("A_MS/ACM")
}

/// Get the appropriate PCM codec name for ffmpeg based on bit depth.
///
/// Used when extracting A_MS/ACM audio that needs transcoding to PCM.
pub fn pcm_codec_from_bit_depth(bit_depth: Option<u8>) -> &'static str {
    match bit_depth.unwrap_or(16) {
        64.. => "pcm_f64le",
        32..=63 => "pcm_s32le",
        24..=31 => "pcm_s24le",
        _ => "pcm_s16le",
    }
}

/// Extract an audio track using ffmpeg.
///
/// This is used as a fallback for codecs that mkvextract can't handle directly,
/// like A_MS/ACM. First tries stream copy, then falls back to PCM transcoding.
///
/// # Arguments
/// * `input_path` - Path to the source MKV file
/// * `audio_stream_index` - The ffmpeg audio stream index (0-based within audio streams)
/// * `output_path` - Path where the audio will be written (should end in .wav)
/// * `bit_depth` - Optional bit depth for PCM conversion
///
/// # Returns
/// `Ok(())` on success, `Err` on failure
pub fn extract_audio_with_ffmpeg(
    input_path: &Path,
    audio_stream_index: usize,
    output_path: &Path,
    bit_depth: Option<u8>,
) -> ExtractionResult<()> {
    if !input_path.exists() {
        return Err(ExtractionError::FileNotFound(input_path.to_path_buf()));
    }

    // First try: stream copy
    let copy_output = Command::new("ffmpeg")
        .args(["-y", "-v", "error", "-nostdin", "-i"])
        .arg(input_path)
        .args([
            "-map",
            &format!("0:a:{}", audio_stream_index),
            "-vn",
            "-sn",
            "-c:a",
            "copy",
        ])
        .arg(output_path)
        .output()
        .map_err(|e| ExtractionError::ExtractionFailed(format!("Failed to run ffmpeg: {}", e)))?;

    if copy_output.status.success() {
        tracing::info!(
            "Extracted audio stream {} with ffmpeg (stream copy) to {}",
            audio_stream_index,
            output_path.display()
        );
        return Ok(());
    }

    // Second try: transcode to PCM
    tracing::debug!(
        "Stream copy failed for audio {}, falling back to PCM transcoding",
        audio_stream_index
    );

    let pcm_codec = pcm_codec_from_bit_depth(bit_depth);
    let pcm_output = Command::new("ffmpeg")
        .args(["-y", "-v", "error", "-nostdin", "-i"])
        .arg(input_path)
        .args([
            "-map",
            &format!("0:a:{}", audio_stream_index),
            "-vn",
            "-sn",
            "-acodec",
            pcm_codec,
        ])
        .arg(output_path)
        .output()
        .map_err(|e| ExtractionError::ExtractionFailed(format!("Failed to run ffmpeg: {}", e)))?;

    if pcm_output.status.success() {
        tracing::info!(
            "Extracted audio stream {} with ffmpeg (transcoded to {}) to {}",
            audio_stream_index,
            pcm_codec,
            output_path.display()
        );
        return Ok(());
    }

    // Both failed
    let stderr = String::from_utf8_lossy(&pcm_output.stderr);
    Err(ExtractionError::ExtractionFailed(format!(
        "Failed to extract audio stream {} with ffmpeg (both stream copy and PCM failed): {}",
        audio_stream_index, stderr
    )))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extension_mapping() {
        assert_eq!(extension_for_codec("A_AAC"), "aac");
        assert_eq!(extension_for_codec("V_MPEG4/ISO/AVC"), "h264");
        assert_eq!(extension_for_codec("S_TEXT/UTF8"), "srt");
        assert_eq!(extension_for_codec("S_TEXT/ASS"), "ass");
        assert_eq!(extension_for_codec("UNKNOWN"), "bin");
    }

    #[test]
    fn nonexistent_file_error() {
        let result = extract_track(
            &Path::new("/nonexistent/file.mkv"),
            0,
            &Path::new("/tmp/output.h264"),
        );
        assert!(matches!(result, Err(ExtractionError::FileNotFound(_))));
    }
}
