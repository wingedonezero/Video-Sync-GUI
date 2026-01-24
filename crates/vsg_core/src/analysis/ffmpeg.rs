//! FFmpeg audio extraction.
//!
//! Extracts audio from video files using FFmpeg, converts to mono,
//! resamples to analysis sample rate, and outputs raw f64 samples.

use std::io::Read;
use std::path::Path;
use std::process::{Command, Stdio};

use crate::analysis::types::{AnalysisError, AnalysisResult, AudioData};

/// Default sample rate for analysis (48kHz provides good accuracy).
pub const DEFAULT_ANALYSIS_SAMPLE_RATE: u32 = 48000;

/// Extract audio from a video file using FFmpeg.
///
/// The audio is:
/// - Converted to mono (channel downmix)
/// - Resampled to the analysis sample rate
/// - Optionally uses SOXR high-quality resampling
/// - Output as raw f64 samples
///
/// # Arguments
/// * `input_path` - Path to the input video file
/// * `sample_rate` - Target sample rate for analysis
/// * `use_soxr` - Whether to use SOXR high-quality resampling
///
/// # Returns
/// AudioData containing the extracted samples.
pub fn extract_audio(
    input_path: &Path,
    sample_rate: u32,
    use_soxr: bool,
) -> AnalysisResult<AudioData> {
    if !input_path.exists() {
        return Err(AnalysisError::SourceNotFound(
            input_path.display().to_string(),
        ));
    }

    // Build FFmpeg command
    let mut cmd = Command::new("ffmpeg");
    cmd.arg("-i")
        .arg(input_path)
        .arg("-vn") // No video
        .arg("-ac")
        .arg("1") // Mono
        .arg("-ar")
        .arg(sample_rate.to_string()); // Sample rate

    // Use SOXR resampler if requested
    if use_soxr {
        cmd.arg("-resampler").arg("soxr");
    }

    // Output raw f64 samples to stdout
    cmd.arg("-f")
        .arg("f64le") // 64-bit float, little endian
        .arg("-acodec")
        .arg("pcm_f64le")
        .arg("pipe:1"); // Output to stdout

    // Suppress FFmpeg's stderr output
    cmd.stderr(Stdio::null()).stdout(Stdio::piped());

    tracing::debug!("Running FFmpeg: {:?}", cmd);

    // Execute FFmpeg
    let mut child = cmd
        .spawn()
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to spawn FFmpeg: {}", e)))?;

    // Read output
    let mut stdout = child
        .stdout
        .take()
        .ok_or_else(|| AnalysisError::FfmpegError("Failed to capture FFmpeg stdout".to_string()))?;

    let mut buffer = Vec::new();
    stdout.read_to_end(&mut buffer).map_err(|e| {
        AnalysisError::FfmpegError(format!("Failed to read FFmpeg output: {}", e))
    })?;

    // Wait for FFmpeg to finish
    let status = child
        .wait()
        .map_err(|e| AnalysisError::FfmpegError(format!("FFmpeg process error: {}", e)))?;

    if !status.success() {
        return Err(AnalysisError::FfmpegError(format!(
            "FFmpeg exited with code: {:?}",
            status.code()
        )));
    }

    // Convert bytes to f64 samples
    let samples = bytes_to_f64_samples(&buffer);

    if samples.is_empty() {
        return Err(AnalysisError::ExtractionError(
            "No audio samples extracted".to_string(),
        ));
    }

    tracing::debug!(
        "Extracted {} samples ({:.2}s) from {}",
        samples.len(),
        samples.len() as f64 / sample_rate as f64,
        input_path.display()
    );

    Ok(AudioData::new(samples, sample_rate))
}

/// Extract a portion of audio from a video file.
///
/// More efficient than extracting all audio when only a portion is needed.
///
/// # Arguments
/// * `input_path` - Path to the input video file
/// * `start_secs` - Start time in seconds
/// * `duration_secs` - Duration to extract in seconds
/// * `sample_rate` - Target sample rate for analysis
/// * `use_soxr` - Whether to use SOXR high-quality resampling
/// * `audio_stream_index` - Optional audio stream index (for `-map 0:a:N`)
pub fn extract_audio_segment(
    input_path: &Path,
    start_secs: f64,
    duration_secs: f64,
    sample_rate: u32,
    use_soxr: bool,
    audio_stream_index: Option<usize>,
) -> AnalysisResult<AudioData> {
    if !input_path.exists() {
        return Err(AnalysisError::SourceNotFound(
            input_path.display().to_string(),
        ));
    }

    // Build FFmpeg command with seek
    let mut cmd = Command::new("ffmpeg");
    cmd.arg("-ss")
        .arg(format!("{:.3}", start_secs)) // Seek to start
        .arg("-i")
        .arg(input_path);

    // Map specific audio stream if index provided
    if let Some(idx) = audio_stream_index {
        cmd.arg("-map").arg(format!("0:a:{}", idx));
    }

    cmd.arg("-t")
        .arg(format!("{:.3}", duration_secs)) // Duration
        .arg("-vn") // No video
        .arg("-ac")
        .arg("1") // Mono
        .arg("-ar")
        .arg(sample_rate.to_string()); // Sample rate

    // Use SOXR resampler if requested
    if use_soxr {
        cmd.arg("-resampler").arg("soxr");
    }

    // Output raw f64 samples to stdout
    cmd.arg("-f")
        .arg("f64le")
        .arg("-acodec")
        .arg("pcm_f64le")
        .arg("pipe:1");

    cmd.stderr(Stdio::null()).stdout(Stdio::piped());

    tracing::debug!("Running FFmpeg (segment): {:?}", cmd);

    let mut child = cmd
        .spawn()
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to spawn FFmpeg: {}", e)))?;

    let mut stdout = child
        .stdout
        .take()
        .ok_or_else(|| AnalysisError::FfmpegError("Failed to capture FFmpeg stdout".to_string()))?;

    let mut buffer = Vec::new();
    stdout.read_to_end(&mut buffer).map_err(|e| {
        AnalysisError::FfmpegError(format!("Failed to read FFmpeg output: {}", e))
    })?;

    let status = child
        .wait()
        .map_err(|e| AnalysisError::FfmpegError(format!("FFmpeg process error: {}", e)))?;

    if !status.success() {
        return Err(AnalysisError::FfmpegError(format!(
            "FFmpeg exited with code: {:?}",
            status.code()
        )));
    }

    let samples = bytes_to_f64_samples(&buffer);

    if samples.is_empty() {
        return Err(AnalysisError::ExtractionError(
            "No audio samples extracted".to_string(),
        ));
    }

    Ok(AudioData::new(samples, sample_rate))
}

/// Get the duration of a media file using FFprobe.
pub fn get_duration(input_path: &Path) -> AnalysisResult<f64> {
    if !input_path.exists() {
        return Err(AnalysisError::SourceNotFound(
            input_path.display().to_string(),
        ));
    }

    let output = Command::new("ffprobe")
        .arg("-v")
        .arg("error")
        .arg("-show_entries")
        .arg("format=duration")
        .arg("-of")
        .arg("default=noprint_wrappers=1:nokey=1")
        .arg(input_path)
        .output()
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to run ffprobe: {}", e)))?;

    if !output.status.success() {
        return Err(AnalysisError::FfmpegError(
            "ffprobe failed to get duration".to_string(),
        ));
    }

    let duration_str = String::from_utf8_lossy(&output.stdout);
    duration_str
        .trim()
        .parse::<f64>()
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to parse duration: {}", e)))
}

/// Convert raw bytes to f64 samples (little-endian).
fn bytes_to_f64_samples(bytes: &[u8]) -> Vec<f64> {
    bytes
        .chunks_exact(8)
        .map(|chunk| {
            let arr: [u8; 8] = chunk.try_into().unwrap();
            f64::from_le_bytes(arr)
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn bytes_to_samples_converts_correctly() {
        // Create bytes for known f64 values
        let val1: f64 = 0.5;
        let val2: f64 = -0.25;

        let mut bytes = Vec::new();
        bytes.extend_from_slice(&val1.to_le_bytes());
        bytes.extend_from_slice(&val2.to_le_bytes());

        let samples = bytes_to_f64_samples(&bytes);

        assert_eq!(samples.len(), 2);
        assert!((samples[0] - 0.5).abs() < 1e-10);
        assert!((samples[1] - (-0.25)).abs() < 1e-10);
    }

    #[test]
    fn bytes_to_samples_handles_partial() {
        // Only 10 bytes - should get 1 sample (8 bytes), ignore remainder
        let bytes = vec![0u8; 10];
        let samples = bytes_to_f64_samples(&bytes);
        assert_eq!(samples.len(), 1);
    }

    #[test]
    fn extract_audio_rejects_missing_file() {
        let result = extract_audio(Path::new("/nonexistent/file.mkv"), 48000, false);
        assert!(matches!(result, Err(AnalysisError::SourceNotFound(_))));
    }
}
