//! Video property detection functions.
//!
//! Uses ffprobe to detect video properties like FPS, resolution, interlacing,
//! duration, and frame count.

use std::path::Path;
use std::process::Command;

use super::timing::parse_fps_fraction;
use super::types::{
    ContentType, FieldOrder, SyncStrategy, VideoCompareResult, VideoProperties,
};
use crate::subtitles::error::FrameError;

/// Detect video properties from a file using ffprobe.
///
/// # Arguments
/// * `path` - Path to video file
///
/// # Returns
/// VideoProperties with detected values, or defaults on failure
///
/// # Logging
/// Logs detection progress with `[VideoProps]` prefix
pub fn detect_properties(path: &Path) -> Result<VideoProperties, FrameError> {
    let filename = path
        .file_name()
        .map(|s| s.to_string_lossy())
        .unwrap_or_default();

    tracing::info!("[VideoProps] Detecting properties for: {}", filename);

    // Default/fallback values
    let mut props = VideoProperties::default();

    // Run ffprobe
    let output = Command::new("ffprobe")
        .args([
            "-v",
            "quiet",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate,avg_frame_rate,field_order,nb_frames,duration,codec_name,width,height",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
        ])
        .arg(path)
        .output()
        .map_err(|e| FrameError::PropertiesFailed(format!("ffprobe execution failed: {}", e)))?;

    if !output.status.success() {
        tracing::warn!("[VideoProps] WARNING: ffprobe failed, using defaults");
        return Ok(props);
    }

    let json_str = String::from_utf8_lossy(&output.stdout);
    let data: serde_json::Value = serde_json::from_str(&json_str).map_err(|e| {
        FrameError::PropertiesFailed(format!("Failed to parse ffprobe JSON: {}", e))
    })?;

    // Check for streams
    let streams = data.get("streams").and_then(|s| s.as_array());
    if streams.map(|s| s.is_empty()).unwrap_or(true) {
        tracing::warn!("[VideoProps] WARNING: No video streams found");
        return Ok(props);
    }

    let stream = &streams.unwrap()[0];
    props.detection_source = "ffprobe".to_string();

    // Parse FPS from r_frame_rate (more reliable than avg_frame_rate)
    if let Some(r_frame_rate) = stream.get("r_frame_rate").and_then(|v| v.as_str()) {
        if let Some(fps) = parse_fps_fraction(r_frame_rate) {
            props.fps = fps;
            // Parse fraction components
            if let Some(idx) = r_frame_rate.find('/') {
                let num: u32 = r_frame_rate[..idx].parse().unwrap_or(24000);
                let denom: u32 = r_frame_rate[idx + 1..].parse().unwrap_or(1001);
                props.fps_fraction = (num, denom);
            }
        }
    }

    // Parse resolution
    if let Some(width) = stream.get("width").and_then(|v| v.as_u64()) {
        props.width = width as u32;
    }
    if let Some(height) = stream.get("height").and_then(|v| v.as_u64()) {
        props.height = height as u32;
    }

    // Parse field_order for interlacing detection
    if let Some(field_order) = stream.get("field_order").and_then(|v| v.as_str()) {
        props.field_order = FieldOrder::from_ffprobe(field_order);
        props.interlaced = matches!(
            props.field_order,
            FieldOrder::TopFieldFirst | FieldOrder::BottomFieldFirst
        );
    }

    // Parse duration - try stream first, then format (MKV often only has format duration)
    if let Some(duration) = stream.get("duration").and_then(|v| v.as_str()) {
        if duration != "N/A" {
            if let Ok(d) = duration.parse::<f64>() {
                props.duration_ms = d * 1000.0;
            }
        }
    }
    // Fallback to format duration
    if props.duration_ms == 0.0 {
        if let Some(format_duration) = data
            .get("format")
            .and_then(|f| f.get("duration"))
            .and_then(|v| v.as_str())
        {
            if format_duration != "N/A" {
                if let Ok(d) = format_duration.parse::<f64>() {
                    props.duration_ms = d * 1000.0;
                }
            }
        }
    }

    // Parse frame count (if available)
    if let Some(nb_frames) = stream.get("nb_frames").and_then(|v| v.as_str()) {
        if nb_frames != "N/A" {
            if let Ok(count) = nb_frames.parse::<u32>() {
                props.frame_count = count;
            }
        }
    }
    // Estimate frame count from duration if not available
    if props.frame_count == 0 && props.duration_ms > 0.0 && props.fps > 0.0 {
        props.frame_count = (props.duration_ms * props.fps / 1000.0) as u32;
    }

    // Detect SD content and DVD characteristics
    props.is_sd = props.height <= 576;

    // DVD detection heuristics
    // NTSC DVD: 720x480 or 704x480
    // PAL DVD: 720x576 or 704x576
    let is_ntsc_dvd = (props.height == 480 || props.height == 486)
        && (props.width == 720 || props.width == 704 || props.width == 640);
    let is_pal_dvd =
        (props.height == 576 || props.height == 578) && (props.width == 720 || props.width == 704);
    props.is_dvd = is_ntsc_dvd || is_pal_dvd;

    // Determine content_type based on multiple factors
    if props.interlaced {
        // Check for telecine characteristics
        // NTSC telecine: 29.97fps interlaced from 24fps film
        if (props.fps - 29.97).abs() < 0.1 && is_ntsc_dvd {
            props.content_type = ContentType::Telecine;
        } else {
            props.content_type = ContentType::Interlaced;
        }
    } else if (props.fps - 29.97).abs() < 0.1 && props.is_sd {
        // 29.97p SD content - could be soft telecine or native
        props.content_type = ContentType::Unknown;
    } else {
        props.content_type = ContentType::Progressive;
    }

    // Log detected properties (matching Python format)
    tracing::info!(
        "[VideoProps] FPS: {:.3} ({}/{})",
        props.fps,
        props.fps_fraction.0,
        props.fps_fraction.1
    );
    tracing::info!(
        "[VideoProps] Resolution: {}x{}",
        props.width,
        props.height
    );
    tracing::info!(
        "[VideoProps] Scan type: {}, Field order: {}",
        if props.interlaced {
            "interlaced"
        } else {
            "progressive"
        },
        props.field_order.name()
    );
    tracing::info!(
        "[VideoProps] Duration: {:.0}ms, Frames: {}",
        props.duration_ms,
        props.frame_count
    );

    // Log content type detection
    if props.is_dvd {
        tracing::info!(
            "[VideoProps] Content type: {} (DVD detected)",
            props.content_type.name()
        );
    } else if props.is_sd {
        tracing::info!(
            "[VideoProps] Content type: {} (SD content)",
            props.content_type.name()
        );
    } else {
        tracing::info!("[VideoProps] Content type: {}", props.content_type.name());
    }

    // Additional notes for specific content types
    if props.content_type == ContentType::Telecine {
        tracing::info!("[VideoProps] NOTE: Telecine detected - IVTC may improve frame matching");
    } else if props.content_type == ContentType::Interlaced {
        tracing::info!(
            "[VideoProps] NOTE: Interlaced content - deinterlacing required for frame matching"
        );
    }

    Ok(props)
}

/// Detect just the FPS from a video file.
///
/// # Arguments
/// * `path` - Path to video file
///
/// # Returns
/// FPS as f64, or 23.976 as fallback
pub fn detect_fps(path: &Path) -> f64 {
    let filename = path
        .file_name()
        .map(|s| s.to_string_lossy())
        .unwrap_or_default();

    tracing::info!("[FPS Detection] Detecting FPS from: {}", filename);

    let output = match Command::new("ffprobe")
        .args([
            "-v",
            "quiet",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "json",
        ])
        .arg(path)
        .output()
    {
        Ok(o) => o,
        Err(_) => {
            tracing::warn!("[FPS Detection] WARNING: ffprobe failed, using default 23.976 fps");
            return 23.976;
        }
    };

    if !output.status.success() {
        tracing::warn!("[FPS Detection] WARNING: ffprobe failed, using default 23.976 fps");
        return 23.976;
    }

    let json_str = String::from_utf8_lossy(&output.stdout);
    let data: serde_json::Value = match serde_json::from_str(&json_str) {
        Ok(d) => d,
        Err(_) => {
            tracing::warn!("[FPS Detection] WARNING: Failed to parse JSON, using default 23.976 fps");
            return 23.976;
        }
    };

    let fps = data
        .get("streams")
        .and_then(|s| s.as_array())
        .and_then(|arr| arr.first())
        .and_then(|stream| stream.get("r_frame_rate"))
        .and_then(|v| v.as_str())
        .and_then(parse_fps_fraction)
        .unwrap_or(23.976);

    tracing::info!("[FPS Detection] Detected FPS: {:.3}", fps);

    fps
}

/// Get video duration in milliseconds.
///
/// # Arguments
/// * `path` - Path to video file
///
/// # Returns
/// Duration in milliseconds, or 0.0 on failure
pub fn get_duration_ms(path: &Path) -> f64 {
    match detect_properties(path) {
        Ok(props) => props.duration_ms,
        Err(_) => 0.0,
    }
}

/// Compare video properties between source and target to determine sync strategy.
///
/// # Arguments
/// * `source_props` - Properties of source video
/// * `target_props` - Properties of target video
///
/// # Returns
/// VideoCompareResult with recommended strategy and warnings
pub fn compare_video_properties(
    source_props: &VideoProperties,
    target_props: &VideoProperties,
) -> VideoCompareResult {
    tracing::info!("[VideoProps] -----------------------------------------");
    tracing::info!("[VideoProps] Comparing source vs target properties...");

    let mut result = VideoCompareResult {
        strategy: SyncStrategy::FrameBased,
        fps_match: true,
        fps_ratio: 1.0,
        interlace_mismatch: false,
        needs_deinterlace: false,
        needs_scaling: false,
        scale_factor: 1.0,
        warnings: Vec::new(),
    };

    // Check FPS match (within 0.1% tolerance)
    let fps_diff_pct = (source_props.fps - target_props.fps).abs() / target_props.fps * 100.0;
    result.fps_ratio = source_props.fps / target_props.fps;

    if fps_diff_pct < 0.1 {
        result.fps_match = true;
        tracing::info!(
            "[VideoProps] FPS: MATCH ({:.3} ~ {:.3})",
            source_props.fps,
            target_props.fps
        );
    } else {
        result.fps_match = false;
        tracing::info!(
            "[VideoProps] FPS: MISMATCH ({:.3} vs {:.3}, diff={:.2}%)",
            source_props.fps,
            target_props.fps,
            fps_diff_pct
        );

        // Check for PAL speedup (23.976 -> 25 = 4.17% faster)
        if result.fps_ratio > 1.04 && result.fps_ratio < 1.05 {
            result.needs_scaling = true;
            result.scale_factor = target_props.fps / source_props.fps;
            result.strategy = SyncStrategy::Scale;
            result.warnings.push(format!(
                "PAL speedup detected (ratio={:.4}), subtitles need scaling",
                result.fps_ratio
            ));
            tracing::info!("[VideoProps] PAL speedup detected - will need subtitle scaling");
        } else if 1.0 / result.fps_ratio > 0.95 && 1.0 / result.fps_ratio < 0.96 {
            // Reverse PAL (25 -> 23.976)
            result.needs_scaling = true;
            result.scale_factor = target_props.fps / source_props.fps;
            result.strategy = SyncStrategy::Scale;
            result
                .warnings
                .push("Reverse PAL detected, subtitles need scaling".to_string());
            tracing::info!("[VideoProps] Reverse PAL detected - will need subtitle scaling");
        } else {
            // Different framerates, use timestamp-based
            result.strategy = SyncStrategy::TimestampBased;
            result
                .warnings
                .push("Different framerates - frame-based matching may be unreliable".to_string());
            tracing::info!(
                "[VideoProps] Different framerates - timestamp-based matching recommended"
            );
        }
    }

    // Check interlacing
    if source_props.interlaced != target_props.interlaced {
        result.interlace_mismatch = true;
        tracing::info!(
            "[VideoProps] Interlacing: MISMATCH (source={}, target={})",
            source_props.interlaced,
            target_props.interlaced
        );
    }

    if source_props.interlaced || target_props.interlaced {
        result.needs_deinterlace = true;
        if result.strategy == SyncStrategy::FrameBased {
            result.strategy = SyncStrategy::Deinterlace;
        }
        result
            .warnings
            .push("Interlaced content detected - frame hashing may be less reliable".to_string());
        tracing::info!(
            "[VideoProps] Interlaced content - will need deinterlace for frame matching"
        );
    }

    // Summary
    tracing::info!(
        "[VideoProps] Recommended strategy: {}",
        result.strategy.name()
    );
    for warn in &result.warnings {
        tracing::warn!("[VideoProps] WARNING: {}", warn);
    }
    tracing::info!("[VideoProps] -----------------------------------------");

    result
}

/// Check if ffprobe is available.
///
/// # Returns
/// true if ffprobe can be executed
pub fn is_ffprobe_available() -> bool {
    Command::new("ffprobe")
        .arg("-version")
        .output()
        .map(|o| o.status.success())
        .unwrap_or(false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_is_ffprobe_available() {
        // This just tests that the function doesn't panic
        let _available = is_ffprobe_available();
    }

    #[test]
    fn test_compare_video_properties_same_fps() {
        let source = VideoProperties {
            fps: 23.976,
            ..Default::default()
        };
        let target = VideoProperties {
            fps: 23.976,
            ..Default::default()
        };

        let result = compare_video_properties(&source, &target);
        assert!(result.fps_match);
        assert_eq!(result.strategy, SyncStrategy::FrameBased);
    }

    #[test]
    fn test_compare_video_properties_pal_speedup() {
        let source = VideoProperties {
            fps: 23.976,
            ..Default::default()
        };
        let target = VideoProperties {
            fps: 25.0,
            ..Default::default()
        };

        let result = compare_video_properties(&source, &target);
        assert!(!result.fps_match);
        assert!(result.needs_scaling);
        assert_eq!(result.strategy, SyncStrategy::Scale);
    }

    #[test]
    fn test_compare_video_properties_interlaced() {
        let source = VideoProperties {
            fps: 29.97,
            interlaced: true,
            field_order: FieldOrder::TopFieldFirst,
            ..Default::default()
        };
        let target = VideoProperties {
            fps: 29.97,
            interlaced: false,
            ..Default::default()
        };

        let result = compare_video_properties(&source, &target);
        assert!(result.interlace_mismatch);
        assert!(result.needs_deinterlace);
    }

    #[test]
    fn test_default_video_properties() {
        let props = VideoProperties::default();
        assert!((props.fps - 23.976).abs() < 0.001);
        assert_eq!(props.fps_fraction, (24000, 1001));
        assert!(!props.interlaced);
        assert_eq!(props.content_type, ContentType::Progressive);
    }
}
