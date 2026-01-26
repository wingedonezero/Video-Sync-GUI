//! Chapter keyframe snapping.
//!
//! Provides functionality to snap chapter timestamps to the nearest
//! video keyframes for better seeking behavior.

use std::path::Path;
use std::process::Command;

use super::types::{ChapterData, ChapterError, ChapterResult, KeyframeInfo};

/// Snap mode for chapter-to-keyframe alignment.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum SnapMode {
    /// Snap to the nearest keyframe (before or after).
    #[default]
    Nearest,
    /// Snap to the previous keyframe (always before or at the chapter time).
    Previous,
    /// Snap to the next keyframe (always after or at the chapter time).
    Next,
}

/// Snap all chapter start times to keyframes.
///
/// # Arguments
/// * `data` - The chapter data to modify (in place)
/// * `keyframes` - Keyframe information from the video
/// * `mode` - How to snap to keyframes
///
/// Note: This function snaps all chapters regardless of distance.
/// Use `snap_chapters_with_threshold` to enforce a maximum snap distance.
pub fn snap_chapters(data: &mut ChapterData, keyframes: &KeyframeInfo, mode: SnapMode) {
    snap_chapters_with_threshold(data, keyframes, mode, None);
}

/// Snap chapter start times to keyframes with optional threshold enforcement.
///
/// # Arguments
/// * `data` - The chapter data to modify (in place)
/// * `keyframes` - Keyframe information from the video
/// * `mode` - How to snap to keyframes
/// * `threshold_ms` - Maximum distance (in ms) to snap. Chapters farther away are skipped.
///                    Pass `None` to snap all chapters regardless of distance.
///
/// # Returns
/// Statistics about the snapping operation.
pub fn snap_chapters_with_threshold(
    data: &mut ChapterData,
    keyframes: &KeyframeInfo,
    mode: SnapMode,
    threshold_ms: Option<i64>,
) -> SnapStats {
    let threshold_ns = threshold_ms.map(|ms| ms * 1_000_000);

    if keyframes.timestamps_ns.is_empty() {
        tracing::warn!("No keyframes available for snapping");
        return SnapStats {
            chapter_count: data.len(),
            already_aligned: 0,
            moved: 0,
            skipped: data.len(),
            max_shift_ms: 0,
            avg_shift_ms: 0.0,
        };
    }

    tracing::debug!(
        "Snapping {} chapters to keyframes (mode: {:?}, threshold: {:?}ms)",
        data.len(),
        mode,
        threshold_ms
    );

    let mut already_aligned = 0;
    let mut moved = 0;
    let mut skipped = 0;
    let mut total_shift_ns: i64 = 0;
    let mut max_shift_ns: i64 = 0;

    for chapter in data.iter_mut() {
        let original = chapter.start_ns;
        let snapped = match mode {
            SnapMode::Nearest => keyframes.nearest(original),
            SnapMode::Previous => keyframes.previous(original),
            SnapMode::Next => keyframes.next(original),
        };

        if let Some(new_start) = snapped {
            let shift_ns = (new_start as i64 - original as i64).abs();
            let shift_ms = shift_ns / 1_000_000;

            if new_start == original {
                // Already on keyframe
                already_aligned += 1;
                tracing::trace!(
                    "Chapter '{}' ({}) - already on keyframe",
                    chapter.display_name().unwrap_or("unnamed"),
                    format_timestamp_for_log(original)
                );
            } else if threshold_ns.is_none() || shift_ns <= threshold_ns.unwrap() {
                // Within threshold (or no threshold), snap it
                tracing::trace!(
                    "Chapter '{}': {} -> {} ({:+}ms)",
                    chapter.display_name().unwrap_or("unnamed"),
                    format_timestamp_for_log(original),
                    format_timestamp_for_log(new_start),
                    (new_start as i64 - original as i64) / 1_000_000
                );
                chapter.start_ns = new_start;
                moved += 1;
                total_shift_ns += shift_ns;
                max_shift_ns = max_shift_ns.max(shift_ns);
            } else {
                // Exceeds threshold, skip
                skipped += 1;
                tracing::trace!(
                    "Chapter '{}' ({}) - skipped ({}ms exceeds threshold of {}ms)",
                    chapter.display_name().unwrap_or("unnamed"),
                    format_timestamp_for_log(original),
                    shift_ms,
                    threshold_ms.unwrap_or(0)
                );
            }
        }
    }

    // Re-sort after snapping (order might change with aggressive snapping)
    data.sort_by_time();

    let avg_shift_ms = if moved > 0 {
        (total_shift_ns as f64 / moved as f64) / 1_000_000.0
    } else {
        0.0
    };

    SnapStats {
        chapter_count: data.len(),
        already_aligned,
        moved,
        skipped,
        max_shift_ms: max_shift_ns / 1_000_000,
        avg_shift_ms,
    }
}

/// Format timestamp for logging (HH:MM:SS.mmm)
fn format_timestamp_for_log(ns: u64) -> String {
    let total_ms = ns / 1_000_000;
    let ms = total_ms % 1000;
    let total_secs = total_ms / 1000;
    let secs = total_secs % 60;
    let total_mins = total_secs / 60;
    let mins = total_mins % 60;
    let hours = total_mins / 60;
    format!("{:02}:{:02}:{:02}.{:03}", hours, mins, secs, ms)
}

/// Create a new ChapterData with snapped timestamps.
pub fn snap_chapters_copy(
    data: &ChapterData,
    keyframes: &KeyframeInfo,
    mode: SnapMode,
) -> ChapterData {
    let mut result = data.clone();
    snap_chapters(&mut result, keyframes, mode);
    result
}

/// Extract keyframe timestamps from a video file.
///
/// Uses ffprobe to get keyframe (I-frame) timestamps from the video stream.
pub fn extract_keyframes(video_path: &Path) -> ChapterResult<KeyframeInfo> {
    tracing::debug!("Extracting keyframes from {}", video_path.display());

    // Use ffprobe to get keyframe timestamps
    // -select_streams v:0 = first video stream
    // -show_frames = show frame info
    // -show_entries frame=pts_time,pict_type = only show timestamp and frame type
    // -of csv=p=0 = output as CSV without headers
    let output = Command::new("ffprobe")
        .args([
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_frames",
            "-show_entries",
            "frame=pts_time,pict_type",
            "-of",
            "csv=p=0",
        ])
        .arg(video_path)
        .output()
        .map_err(|e| ChapterError::KeyframeError(format!("Failed to run ffprobe: {}", e)))?;

    if !output.status.success() {
        return Err(ChapterError::KeyframeError(format!(
            "ffprobe failed: {}",
            String::from_utf8_lossy(&output.stderr)
        )));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let mut timestamps_ns = Vec::new();

    for line in stdout.lines() {
        let parts: Vec<&str> = line.split(',').collect();
        if parts.len() >= 2 {
            // Check if it's a keyframe (I-frame)
            if parts[1].trim() == "I" {
                if let Ok(pts_secs) = parts[0].parse::<f64>() {
                    let pts_ns = (pts_secs * 1_000_000_000.0) as u64;
                    timestamps_ns.push(pts_ns);
                }
            }
        }
    }

    tracing::info!(
        "Found {} keyframes in {}",
        timestamps_ns.len(),
        video_path.display()
    );

    Ok(KeyframeInfo::new(timestamps_ns))
}

/// Extract keyframes with a maximum count limit.
///
/// For very long videos, we might want to limit keyframe extraction.
pub fn extract_keyframes_limited(
    video_path: &Path,
    max_keyframes: usize,
) -> ChapterResult<KeyframeInfo> {
    let mut info = extract_keyframes(video_path)?;

    if info.timestamps_ns.len() > max_keyframes {
        tracing::debug!(
            "Limiting keyframes from {} to {}",
            info.timestamps_ns.len(),
            max_keyframes
        );
        info.timestamps_ns.truncate(max_keyframes);
    }

    Ok(info)
}

/// Calculate statistics about chapter-keyframe alignment.
#[derive(Debug, Clone)]
pub struct SnapStats {
    /// Number of chapters processed.
    pub chapter_count: usize,
    /// Number of chapters that were already on keyframes.
    pub already_aligned: usize,
    /// Number of chapters that were moved.
    pub moved: usize,
    /// Number of chapters skipped (exceeded threshold).
    pub skipped: usize,
    /// Maximum shift applied (in milliseconds).
    pub max_shift_ms: i64,
    /// Average shift applied (in milliseconds).
    pub avg_shift_ms: f64,
}

/// Calculate snapping statistics without modifying the chapters.
///
/// # Arguments
/// * `data` - The chapter data to analyze
/// * `keyframes` - Keyframe information from the video
/// * `mode` - How to snap to keyframes
/// * `threshold_ms` - Maximum distance (in ms) to consider a valid snap.
///                    Pass `None` to count all snaps regardless of distance.
pub fn calculate_snap_stats(
    data: &ChapterData,
    keyframes: &KeyframeInfo,
    mode: SnapMode,
    threshold_ms: Option<i64>,
) -> SnapStats {
    let threshold_ns = threshold_ms.map(|ms| ms * 1_000_000);
    let mut already_aligned = 0;
    let mut moved = 0;
    let mut skipped = 0;
    let mut total_shift_ns: i64 = 0;
    let mut max_shift_ns: i64 = 0;

    for chapter in data.iter() {
        let original = chapter.start_ns;
        let snapped = match mode {
            SnapMode::Nearest => keyframes.nearest(original),
            SnapMode::Previous => keyframes.previous(original),
            SnapMode::Next => keyframes.next(original),
        };

        if let Some(new_start) = snapped {
            let shift_ns = (new_start as i64 - original as i64).abs();
            if new_start == original {
                already_aligned += 1;
            } else if threshold_ns.is_none() || shift_ns <= threshold_ns.unwrap() {
                moved += 1;
                total_shift_ns += shift_ns;
                max_shift_ns = max_shift_ns.max(shift_ns);
            } else {
                skipped += 1;
            }
        }
    }

    let avg_shift_ms = if moved > 0 {
        (total_shift_ns as f64 / moved as f64) / 1_000_000.0
    } else {
        0.0
    };

    SnapStats {
        chapter_count: data.len(),
        already_aligned,
        moved,
        skipped,
        max_shift_ms: max_shift_ns / 1_000_000,
        avg_shift_ms,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chapters::types::ChapterEntry;

    fn create_test_keyframes() -> KeyframeInfo {
        // Keyframes at 0, 2, 4, 6, 8, 10 seconds
        KeyframeInfo::new(vec![
            0,
            2_000_000_000,
            4_000_000_000,
            6_000_000_000,
            8_000_000_000,
            10_000_000_000,
        ])
    }

    fn create_test_chapters() -> ChapterData {
        let mut data = ChapterData::new();
        // Chapter at 0.0s (on keyframe)
        data.add_chapter(ChapterEntry::new(0).with_name("Intro", "eng"));
        // Chapter at 2.5s (between keyframes)
        data.add_chapter(ChapterEntry::new(2_500_000_000).with_name("Act 1", "eng"));
        // Chapter at 4.0s (on keyframe)
        data.add_chapter(ChapterEntry::new(4_000_000_000).with_name("Act 2", "eng"));
        // Chapter at 7.9s (close to 8s keyframe)
        data.add_chapter(ChapterEntry::new(7_900_000_000).with_name("Act 3", "eng"));
        data
    }

    #[test]
    fn snap_nearest() {
        let mut data = create_test_chapters();
        let keyframes = create_test_keyframes();
        snap_chapters(&mut data, &keyframes, SnapMode::Nearest);

        assert_eq!(data.chapters[0].start_ns, 0); // Already on keyframe
        assert_eq!(data.chapters[1].start_ns, 2_000_000_000); // 2.5s -> 2s (nearest)
        assert_eq!(data.chapters[2].start_ns, 4_000_000_000); // Already on keyframe
        assert_eq!(data.chapters[3].start_ns, 8_000_000_000); // 7.9s -> 8s (nearest)
    }

    #[test]
    fn snap_previous() {
        let mut data = create_test_chapters();
        let keyframes = create_test_keyframes();
        snap_chapters(&mut data, &keyframes, SnapMode::Previous);

        assert_eq!(data.chapters[0].start_ns, 0);
        assert_eq!(data.chapters[1].start_ns, 2_000_000_000); // 2.5s -> 2s (previous)
        assert_eq!(data.chapters[2].start_ns, 4_000_000_000);
        assert_eq!(data.chapters[3].start_ns, 6_000_000_000); // 7.9s -> 6s (previous)
    }

    #[test]
    fn snap_next() {
        let mut data = create_test_chapters();
        let keyframes = create_test_keyframes();
        snap_chapters(&mut data, &keyframes, SnapMode::Next);

        assert_eq!(data.chapters[0].start_ns, 0);
        assert_eq!(data.chapters[1].start_ns, 4_000_000_000); // 2.5s -> 4s (next)
        assert_eq!(data.chapters[2].start_ns, 4_000_000_000);
        assert_eq!(data.chapters[3].start_ns, 8_000_000_000); // 7.9s -> 8s (next)
    }

    #[test]
    fn snap_stats() {
        let data = create_test_chapters();
        let keyframes = create_test_keyframes();
        let stats = calculate_snap_stats(&data, &keyframes, SnapMode::Nearest, None);

        assert_eq!(stats.chapter_count, 4);
        assert_eq!(stats.already_aligned, 2); // 0s and 4s
        assert_eq!(stats.moved, 2); // 2.5s and 7.9s
        assert_eq!(stats.skipped, 0); // No threshold
    }

    #[test]
    fn snap_stats_with_threshold() {
        let data = create_test_chapters();
        let keyframes = create_test_keyframes();
        // 250ms threshold - 2.5s->2s is 500ms so it should be skipped
        let stats = calculate_snap_stats(&data, &keyframes, SnapMode::Nearest, Some(250));

        assert_eq!(stats.chapter_count, 4);
        assert_eq!(stats.already_aligned, 2); // 0s and 4s
        assert_eq!(stats.moved, 1); // Only 7.9s->8s (100ms)
        assert_eq!(stats.skipped, 1); // 2.5s->2s exceeds threshold
    }

    #[test]
    fn empty_keyframes_is_noop() {
        let original = create_test_chapters();
        let mut data = original.clone();
        let empty = KeyframeInfo::new(vec![]);
        snap_chapters(&mut data, &empty, SnapMode::Nearest);

        assert_eq!(data.chapters[0].start_ns, original.chapters[0].start_ns);
        assert_eq!(data.chapters[1].start_ns, original.chapters[1].start_ns);
    }
}
