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
    stdout
        .read_to_end(&mut buffer)
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to read FFmpeg output: {}", e)))?;

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
    stdout
        .read_to_end(&mut buffer)
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to read FFmpeg output: {}", e)))?;

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

/// Extract full audio from a video file to memory.
///
/// This decodes the entire audio track once, which is more efficient
/// when multiple chunks need to be analyzed (avoids repeated FFmpeg calls).
///
/// # Arguments
/// * `input_path` - Path to the input video file
/// * `sample_rate` - Target sample rate for analysis
/// * `use_soxr` - Whether to use SOXR high-quality resampling
/// * `audio_stream_index` - Optional audio stream index (for `-map 0:a:N`)
pub fn extract_full_audio(
    input_path: &Path,
    sample_rate: u32,
    use_soxr: bool,
    audio_stream_index: Option<usize>,
) -> AnalysisResult<AudioData> {
    if !input_path.exists() {
        return Err(AnalysisError::SourceNotFound(
            input_path.display().to_string(),
        ));
    }

    // Build FFmpeg command
    let mut cmd = Command::new("ffmpeg");
    cmd.arg("-i").arg(input_path);

    // Map specific audio stream if index provided
    if let Some(idx) = audio_stream_index {
        cmd.arg("-map").arg(format!("0:a:{}", idx));
    }

    cmd.arg("-vn") // No video
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

    tracing::debug!("Running FFmpeg (full audio): {:?}", cmd);

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
    stdout
        .read_to_end(&mut buffer)
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to read FFmpeg output: {}", e)))?;

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

    let duration_secs = samples.len() as f64 / sample_rate as f64;
    tracing::info!(
        "Extracted {} samples ({:.2}s) from {}",
        samples.len(),
        duration_secs,
        input_path.display()
    );

    Ok(AudioData::new(samples, sample_rate))
}

/// Container delay information for a stream.
#[derive(Debug, Clone)]
pub struct StreamDelay {
    /// Stream index.
    pub index: usize,
    /// Stream type ("audio", "video", "subtitle").
    pub stream_type: String,
    /// Language tag if available.
    pub language: Option<String>,
    /// Container delay in milliseconds (start_time relative to 0).
    pub delay_ms: f64,
}

/// Get container delays for all streams in a media file.
///
/// Container delays come from the "start_time" field in ffprobe output.
/// These delays are embedded in the container and affect when each stream
/// starts playing relative to the container timeline.
///
/// # Returns
/// Vector of StreamDelay for each stream in the file.
pub fn get_container_delays(input_path: &Path) -> AnalysisResult<Vec<StreamDelay>> {
    if !input_path.exists() {
        return Err(AnalysisError::SourceNotFound(
            input_path.display().to_string(),
        ));
    }

    // Use ffprobe with JSON output to get stream information
    let output = Command::new("ffprobe")
        .arg("-v")
        .arg("quiet")
        .arg("-print_format")
        .arg("json")
        .arg("-show_streams")
        .arg(input_path)
        .output()
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to run ffprobe: {}", e)))?;

    if !output.status.success() {
        return Err(AnalysisError::FfmpegError(
            "ffprobe failed to get stream info".to_string(),
        ));
    }

    // Parse JSON output
    let json_str = String::from_utf8_lossy(&output.stdout);
    let json: serde_json::Value = serde_json::from_str(&json_str)
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to parse ffprobe JSON: {}", e)))?;

    let mut delays = Vec::new();

    if let Some(streams) = json.get("streams").and_then(|s| s.as_array()) {
        for (idx, stream) in streams.iter().enumerate() {
            let stream_type = stream
                .get("codec_type")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string();

            // Get start_time - this is the container delay
            let start_time = stream
                .get("start_time")
                .and_then(|v| v.as_str())
                .and_then(|s| s.parse::<f64>().ok())
                .unwrap_or(0.0);

            // Convert to milliseconds
            let delay_ms = start_time * 1000.0;

            // Get language from tags
            let language = stream
                .get("tags")
                .and_then(|t| t.get("language"))
                .and_then(|v| v.as_str())
                .map(|s| s.to_string());

            delays.push(StreamDelay {
                index: idx,
                stream_type,
                language,
                delay_ms,
            });
        }
    }

    Ok(delays)
}

/// Get container delay for audio streams, relative to video.
///
/// This calculates the audio-to-video delay, which is what matters for sync.
/// If the video starts at 100ms and audio starts at 150ms, the relative
/// audio delay is +50ms.
///
/// # Returns
/// Map of audio stream index -> relative delay in milliseconds
pub fn get_audio_container_delays_relative(
    input_path: &Path,
) -> AnalysisResult<std::collections::HashMap<usize, f64>> {
    let delays = get_container_delays(input_path)?;

    // Find video stream delay (use first video track)
    let video_delay = delays
        .iter()
        .find(|d| d.stream_type == "video")
        .map(|d| d.delay_ms)
        .unwrap_or(0.0);

    // Calculate relative delays for audio streams
    let mut audio_delays = std::collections::HashMap::new();
    let mut audio_idx = 0;

    for delay in &delays {
        if delay.stream_type == "audio" {
            // Relative delay = audio start time - video start time
            let relative_delay = delay.delay_ms - video_delay;
            audio_delays.insert(audio_idx, relative_delay);
            audio_idx += 1;
        }
    }

    Ok(audio_delays)
}

/// Get the video framerate of a media file using FFprobe.
///
/// Returns the average frame rate of the first video stream.
/// Used for PAL drift detection (25fps indicates potential NTSC→PAL conversion).
pub fn get_framerate(input_path: &Path) -> AnalysisResult<f64> {
    if !input_path.exists() {
        return Err(AnalysisError::SourceNotFound(
            input_path.display().to_string(),
        ));
    }

    let output = Command::new("ffprobe")
        .arg("-v")
        .arg("error")
        .arg("-select_streams")
        .arg("v:0")
        .arg("-show_entries")
        .arg("stream=avg_frame_rate")
        .arg("-of")
        .arg("default=noprint_wrappers=1:nokey=1")
        .arg(input_path)
        .output()
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to run ffprobe: {}", e)))?;

    if !output.status.success() {
        return Err(AnalysisError::FfmpegError(
            "ffprobe failed to get framerate".to_string(),
        ));
    }

    let fps_str = String::from_utf8_lossy(&output.stdout);
    let fps_str = fps_str.trim();

    // FFprobe returns framerate as a fraction (e.g., "24000/1001" or "25/1")
    if fps_str.contains('/') {
        let parts: Vec<&str> = fps_str.split('/').collect();
        if parts.len() == 2 {
            let num: f64 = parts[0]
                .parse()
                .map_err(|e| AnalysisError::FfmpegError(format!("Failed to parse framerate numerator: {}", e)))?;
            let den: f64 = parts[1]
                .parse()
                .map_err(|e| AnalysisError::FfmpegError(format!("Failed to parse framerate denominator: {}", e)))?;

            if den == 0.0 {
                return Err(AnalysisError::FfmpegError(
                    "Invalid framerate: division by zero".to_string(),
                ));
            }

            return Ok(num / den);
        }
    }

    // Try parsing as a plain number
    fps_str
        .parse::<f64>()
        .map_err(|e| AnalysisError::FfmpegError(format!("Failed to parse framerate: {}", e)))
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
