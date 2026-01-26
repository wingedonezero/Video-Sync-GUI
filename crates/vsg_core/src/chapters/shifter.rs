//! Chapter time shifting operations.
//!
//! Provides functionality to shift chapter timestamps by a fixed offset,
//! typically used to compensate for audio/video sync delays.

use super::types::{ChapterData, ChapterEntry};

/// Shift all chapter timestamps by the given offset.
///
/// Positive offset shifts chapters forward in time (adds time).
/// Negative offset shifts chapters backward in time (subtracts time).
///
/// Timestamps are clamped to zero (won't go negative).
///
/// # Arguments
/// * `data` - The chapter data to modify (in place)
/// * `offset_ms` - Offset in milliseconds (can be negative)
pub fn shift_chapters(data: &mut ChapterData, offset_ms: i64) {
    if offset_ms == 0 {
        return;
    }

    let offset_ns = offset_ms * 1_000_000;

    tracing::debug!(
        "Shifting {} chapters by {}ms ({}ns)",
        data.len(),
        offset_ms,
        offset_ns
    );

    for chapter in data.iter_mut() {
        shift_chapter(chapter, offset_ns);
    }
}

/// Shift a single chapter entry by the given offset.
fn shift_chapter(chapter: &mut ChapterEntry, offset_ns: i64) {
    // Shift start time (clamp to 0)
    chapter.start_ns = if offset_ns >= 0 {
        chapter.start_ns.saturating_add(offset_ns as u64)
    } else {
        chapter.start_ns.saturating_sub(offset_ns.unsigned_abs())
    };

    // Shift end time if present
    if let Some(end) = chapter.end_ns {
        chapter.end_ns = Some(if offset_ns >= 0 {
            end.saturating_add(offset_ns as u64)
        } else {
            end.saturating_sub(offset_ns.unsigned_abs())
        });
    }
}

/// Create a new ChapterData with shifted timestamps.
///
/// This is a non-mutating version that returns a new copy.
pub fn shift_chapters_copy(data: &ChapterData, offset_ms: i64) -> ChapterData {
    let mut result = data.clone();
    shift_chapters(&mut result, offset_ms);
    result
}

/// Shift chapters and remove any that would have negative start times.
///
/// Unlike `shift_chapters` which clamps to zero, this removes chapters
/// that would start before zero after shifting.
pub fn shift_chapters_strict(data: &mut ChapterData, offset_ms: i64) {
    if offset_ms == 0 {
        return;
    }

    let offset_ns = offset_ms * 1_000_000;

    // If shifting forward, no chapters will be removed
    if offset_ns >= 0 {
        shift_chapters(data, offset_ms);
        return;
    }

    let min_start_ns = offset_ns.unsigned_abs();

    // Keep only chapters that won't go negative
    data.chapters.retain(|ch| ch.start_ns >= min_start_ns);

    // Shift the remaining chapters
    shift_chapters(data, offset_ms);
}

/// Calculate the minimum shift that would keep all chapters non-negative.
///
/// Returns the maximum negative offset that can be applied without
/// any chapter having a negative start time.
pub fn max_negative_shift(data: &ChapterData) -> i64 {
    data.chapters
        .iter()
        .map(|ch| ch.start_ns as i64)
        .min()
        .map(|min_ns| -min_ns / 1_000_000)
        .unwrap_or(0)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn create_test_data() -> ChapterData {
        let mut data = ChapterData::new();
        data.add_chapter(
            ChapterEntry::new(1_000_000_000) // 1 second
                .with_end(5_000_000_000)
                .with_name("Chapter 1", "eng"),
        );
        data.add_chapter(
            ChapterEntry::new(5_000_000_000) // 5 seconds
                .with_end(10_000_000_000)
                .with_name("Chapter 2", "eng"),
        );
        data
    }

    #[test]
    fn shift_forward() {
        let mut data = create_test_data();
        shift_chapters(&mut data, 500); // +500ms

        assert_eq!(data.chapters[0].start_ns, 1_500_000_000);
        assert_eq!(data.chapters[0].end_ns, Some(5_500_000_000));
        assert_eq!(data.chapters[1].start_ns, 5_500_000_000);
    }

    #[test]
    fn shift_backward() {
        let mut data = create_test_data();
        shift_chapters(&mut data, -500); // -500ms

        assert_eq!(data.chapters[0].start_ns, 500_000_000);
        assert_eq!(data.chapters[0].end_ns, Some(4_500_000_000));
        assert_eq!(data.chapters[1].start_ns, 4_500_000_000);
    }

    #[test]
    fn shift_clamps_to_zero() {
        let mut data = create_test_data();
        shift_chapters(&mut data, -2000); // -2 seconds

        // First chapter starts at 1s, shifted by -2s = clamped to 0
        assert_eq!(data.chapters[0].start_ns, 0);
        // Second chapter starts at 5s, shifted by -2s = 3s
        assert_eq!(data.chapters[1].start_ns, 3_000_000_000);
    }

    #[test]
    fn shift_strict_removes_negative() {
        let mut data = create_test_data();
        shift_chapters_strict(&mut data, -2000); // -2 seconds

        // First chapter would go negative, so it's removed
        assert_eq!(data.len(), 1);
        assert_eq!(data.chapters[0].display_name(), Some("Chapter 2"));
        assert_eq!(data.chapters[0].start_ns, 3_000_000_000);
    }

    #[test]
    fn max_negative_shift_calculation() {
        let data = create_test_data();
        // First chapter at 1s, so max negative shift is -1000ms
        assert_eq!(max_negative_shift(&data), -1000);
    }

    #[test]
    fn zero_shift_is_noop() {
        let original = create_test_data();
        let mut data = original.clone();
        shift_chapters(&mut data, 0);

        assert_eq!(data.chapters[0].start_ns, original.chapters[0].start_ns);
        assert_eq!(data.chapters[1].start_ns, original.chapters[1].start_ns);
    }
}
