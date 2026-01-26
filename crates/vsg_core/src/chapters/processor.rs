//! Chapter processing operations.
//!
//! Provides post-extraction processing for chapters:
//! - Deduplication (remove chapters at identical timestamps)
//! - Normalization (fix end times for seamless playback)
//! - Renaming (standardize chapter names)

use super::types::{ChapterData, ChapterName};

/// Remove duplicate chapters at the same timestamp.
///
/// When multiple chapters have the same start time, keeps only the first one.
/// Returns the number of duplicates removed.
pub fn deduplicate_chapters(data: &mut ChapterData) -> usize {
    if data.chapters.len() < 2 {
        return 0;
    }

    // Sort by time first
    data.sort_by_time();

    let original_count = data.chapters.len();
    let mut seen_starts = std::collections::HashSet::new();

    data.chapters.retain(|chapter| {
        if seen_starts.contains(&chapter.start_ns) {
            false // Duplicate, remove it
        } else {
            seen_starts.insert(chapter.start_ns);
            true
        }
    });

    let removed = original_count - data.chapters.len();
    if removed > 0 {
        tracing::debug!("Removed {} duplicate chapters", removed);
    }
    removed
}

/// Normalize chapter end times for seamless playback.
///
/// Sets each chapter's end time to the next chapter's start time,
/// creating seamless chapters without gaps. For the last chapter,
/// sets end time to max(start + 1s, original_end).
///
/// Returns the number of chapters modified.
pub fn normalize_chapter_ends(data: &mut ChapterData) -> usize {
    if data.chapters.is_empty() {
        return 0;
    }

    // Sort first to ensure proper ordering
    data.sort_by_time();

    let mut modified = 0;
    let len = data.chapters.len();

    for i in 0..len {
        let desired_end = if i + 1 < len {
            // Set end to next chapter's start for seamless chapters
            data.chapters[i + 1].start_ns
        } else {
            // Last chapter: max(start + 1s, original_end)
            let min_end = data.chapters[i].start_ns + 1_000_000_000; // start + 1 second
            data.chapters[i].end_ns.map(|e| e.max(min_end)).unwrap_or(min_end)
        };

        let current_end = data.chapters[i].end_ns;
        if current_end != Some(desired_end) {
            data.chapters[i].end_ns = Some(desired_end);
            modified += 1;
        }
    }

    if modified > 0 {
        tracing::debug!("Normalized {} chapter end times", modified);
    }
    modified
}

/// Rename all chapters to a standardized format.
///
/// Renames chapters to "Chapter 01", "Chapter 02", etc.
/// Preserves the original language codes.
///
/// Returns the number of chapters renamed.
pub fn rename_chapters(data: &mut ChapterData) -> usize {
    let mut renamed = 0;

    for (i, chapter) in data.chapters.iter_mut().enumerate() {
        let new_name = format!("Chapter {:02}", i + 1);

        if chapter.names.is_empty() {
            // No name exists, add one
            chapter.names.push(ChapterName {
                name: new_name,
                language: "eng".to_string(),
                language_ietf: Some("en".to_string()),
            });
            renamed += 1;
        } else {
            // Update existing names
            for name in &mut chapter.names {
                if name.name != new_name {
                    name.name = new_name.clone();
                    renamed += 1;
                }
            }
        }
    }

    if renamed > 0 {
        tracing::debug!("Renamed {} chapter names", renamed);
    }
    renamed
}

/// Processing statistics for chapter operations.
#[derive(Debug, Clone, Default)]
pub struct ProcessingStats {
    /// Number of duplicate chapters removed.
    pub duplicates_removed: usize,
    /// Number of chapter ends normalized.
    pub ends_normalized: usize,
    /// Number of chapters renamed.
    pub chapters_renamed: usize,
}

/// Apply all chapter processing operations based on settings.
///
/// # Arguments
/// * `data` - The chapter data to process (in place)
/// * `deduplicate` - Remove duplicate chapters
/// * `normalize_ends` - Fix end times for seamless playback
/// * `rename` - Rename chapters to "Chapter 01", "Chapter 02", etc.
///
/// # Returns
/// Statistics about the processing operations.
pub fn process_chapters(
    data: &mut ChapterData,
    deduplicate: bool,
    normalize_ends: bool,
    rename: bool,
) -> ProcessingStats {
    let mut stats = ProcessingStats::default();

    // Always deduplicate before other operations
    if deduplicate {
        stats.duplicates_removed = deduplicate_chapters(data);
    }

    // Normalize ends after deduplication
    if normalize_ends {
        stats.ends_normalized = normalize_chapter_ends(data);
    }

    // Rename last (so numbering is correct after deduplication)
    if rename {
        stats.chapters_renamed = rename_chapters(data);
    }

    stats
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::chapters::types::ChapterEntry;

    fn create_test_chapters() -> ChapterData {
        let mut data = ChapterData::new();
        data.add_chapter(ChapterEntry::new(0).with_name("Opening", "eng"));
        data.add_chapter(ChapterEntry::new(60_000_000_000).with_name("Part A", "eng")); // 1 min
        data.add_chapter(ChapterEntry::new(120_000_000_000).with_name("Part B", "eng")); // 2 min
        data
    }

    #[test]
    fn test_deduplicate_removes_duplicates() {
        let mut data = create_test_chapters();
        // Add duplicate at same timestamp
        data.add_chapter(ChapterEntry::new(0).with_name("Duplicate Opening", "eng"));

        assert_eq!(data.len(), 4);
        let removed = deduplicate_chapters(&mut data);
        assert_eq!(removed, 1);
        assert_eq!(data.len(), 3);
    }

    #[test]
    fn test_deduplicate_keeps_first() {
        let mut data = ChapterData::new();
        data.add_chapter(ChapterEntry::new(0).with_name("First", "eng"));
        data.add_chapter(ChapterEntry::new(0).with_name("Second", "eng"));

        deduplicate_chapters(&mut data);
        assert_eq!(data.chapters[0].display_name(), Some("First"));
    }

    #[test]
    fn test_normalize_creates_seamless() {
        let mut data = create_test_chapters();
        normalize_chapter_ends(&mut data);

        // First chapter should end at second chapter's start
        assert_eq!(data.chapters[0].end_ns, Some(60_000_000_000));
        // Second should end at third's start
        assert_eq!(data.chapters[1].end_ns, Some(120_000_000_000));
        // Last should have end = start + 1s
        assert_eq!(data.chapters[2].end_ns, Some(121_000_000_000));
    }

    #[test]
    fn test_rename_chapters() {
        let mut data = create_test_chapters();
        rename_chapters(&mut data);

        assert_eq!(data.chapters[0].display_name(), Some("Chapter 01"));
        assert_eq!(data.chapters[1].display_name(), Some("Chapter 02"));
        assert_eq!(data.chapters[2].display_name(), Some("Chapter 03"));
    }

    #[test]
    fn test_process_all() {
        let mut data = create_test_chapters();
        data.add_chapter(ChapterEntry::new(0).with_name("Duplicate", "eng"));

        let stats = process_chapters(&mut data, true, true, true);

        assert_eq!(stats.duplicates_removed, 1);
        assert!(stats.ends_normalized > 0);
        assert!(stats.chapters_renamed > 0);
        assert_eq!(data.len(), 3);
    }
}
