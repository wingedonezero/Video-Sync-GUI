//! Chapter processing operations.
//!
//! Provides post-extraction processing for chapters:
//! - Deduplication (remove chapters at identical timestamps)
//! - Normalization (fix end times for seamless playback)
//! - Renaming (standardize chapter names)

use super::types::{ChapterData, ChapterName, format_timestamp_ns};

/// Detail about a removed duplicate chapter.
#[derive(Debug, Clone)]
pub struct DuplicateInfo {
    /// The name of the removed chapter.
    pub name: String,
    /// The timestamp where the duplicate was found.
    pub timestamp_ns: u64,
}

/// Remove duplicate chapters at the same timestamp.
///
/// When multiple chapters have the same start time, keeps only the first one.
/// Returns details about removed duplicates.
pub fn deduplicate_chapters(data: &mut ChapterData) -> Vec<DuplicateInfo> {
    if data.chapters.len() < 2 {
        return Vec::new();
    }

    // Sort by time first
    data.sort_by_time();

    let mut removed = Vec::new();
    let mut seen_starts = std::collections::HashSet::new();

    // Collect info about duplicates before removing
    for chapter in &data.chapters {
        if seen_starts.contains(&chapter.start_ns) {
            removed.push(DuplicateInfo {
                name: chapter.display_name().unwrap_or("unnamed").to_string(),
                timestamp_ns: chapter.start_ns,
            });
        } else {
            seen_starts.insert(chapter.start_ns);
        }
    }

    // Now remove them
    seen_starts.clear();
    data.chapters.retain(|chapter| {
        if seen_starts.contains(&chapter.start_ns) {
            false
        } else {
            seen_starts.insert(chapter.start_ns);
            true
        }
    });

    if !removed.is_empty() {
        tracing::debug!("Removed {} duplicate chapters", removed.len());
    }
    removed
}

/// Detail about a normalized chapter end time.
#[derive(Debug, Clone)]
pub struct NormalizedEndInfo {
    /// The name of the chapter.
    pub name: String,
    /// The original end time (None if wasn't set).
    pub original_end_ns: Option<u64>,
    /// The new end time.
    pub new_end_ns: u64,
}

impl NormalizedEndInfo {
    /// Format the change for logging.
    pub fn format_change(&self) -> String {
        let orig = self.original_end_ns
            .map(|ns| format_timestamp_ns(ns))
            .unwrap_or_else(|| "none".to_string());
        format!(
            "'{}' end time: {} -> {}",
            self.name,
            orig,
            format_timestamp_ns(self.new_end_ns)
        )
    }
}

/// Normalize chapter end times for seamless playback.
///
/// Sets each chapter's end time to the next chapter's start time,
/// creating seamless chapters without gaps. For the last chapter,
/// sets end time to max(start + 1s, original_end).
///
/// Returns details about each normalized chapter.
pub fn normalize_chapter_ends(data: &mut ChapterData) -> Vec<NormalizedEndInfo> {
    if data.chapters.is_empty() {
        return Vec::new();
    }

    // Sort first to ensure proper ordering
    data.sort_by_time();

    let mut normalized = Vec::new();
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
            normalized.push(NormalizedEndInfo {
                name: data.chapters[i].display_name().unwrap_or("unnamed").to_string(),
                original_end_ns: current_end,
                new_end_ns: desired_end,
            });
            data.chapters[i].end_ns = Some(desired_end);
        }
    }

    if !normalized.is_empty() {
        tracing::debug!("Normalized {} chapter end times", normalized.len());
    }
    normalized
}

/// Detail about a renamed chapter.
#[derive(Debug, Clone)]
pub struct RenamedInfo {
    /// Chapter number (1-indexed).
    pub chapter_number: usize,
    /// Original name (None if chapter had no name).
    pub original_name: Option<String>,
    /// New name.
    pub new_name: String,
    /// Language code (ISO 639-2).
    pub language: String,
    /// IETF language code (BCP 47).
    pub language_ietf: Option<String>,
}

/// Rename all chapters to a standardized format.
///
/// Renames chapters to "Chapter 01", "Chapter 02", etc.
/// Preserves the original language codes.
///
/// Returns details about each renamed chapter.
pub fn rename_chapters(data: &mut ChapterData) -> Vec<RenamedInfo> {
    let mut renamed = Vec::new();

    for (i, chapter) in data.chapters.iter_mut().enumerate() {
        let new_name = format!("Chapter {:02}", i + 1);

        if chapter.names.is_empty() {
            // No name exists, add one
            chapter.names.push(ChapterName {
                name: new_name.clone(),
                language: "eng".to_string(),
                language_ietf: Some("en".to_string()),
            });
            renamed.push(RenamedInfo {
                chapter_number: i + 1,
                original_name: None,
                new_name,
                language: "eng".to_string(),
                language_ietf: Some("en".to_string()),
            });
        } else {
            // Update existing names - track the first one for logging
            let first_name = &chapter.names[0];
            let original = first_name.name.clone();
            let language = first_name.language.clone();
            let language_ietf = first_name.language_ietf.clone();

            let mut was_renamed = false;
            for name in &mut chapter.names {
                if name.name != new_name {
                    name.name = new_name.clone();
                    was_renamed = true;
                }
            }

            if was_renamed {
                renamed.push(RenamedInfo {
                    chapter_number: i + 1,
                    original_name: Some(original),
                    new_name,
                    language,
                    language_ietf,
                });
            }
        }
    }

    if !renamed.is_empty() {
        tracing::debug!("Renamed {} chapters", renamed.len());
    }
    renamed
}

/// Processing results for chapter operations with detailed info.
#[derive(Debug, Clone, Default)]
pub struct ProcessingStats {
    /// Details about removed duplicates.
    pub duplicates: Vec<DuplicateInfo>,
    /// Details about normalized end times.
    pub normalized: Vec<NormalizedEndInfo>,
    /// Details about renamed chapters.
    pub renamed: Vec<RenamedInfo>,
}

impl ProcessingStats {
    /// Number of duplicate chapters removed.
    pub fn duplicates_removed(&self) -> usize {
        self.duplicates.len()
    }

    /// Number of chapter ends normalized.
    pub fn ends_normalized(&self) -> usize {
        self.normalized.len()
    }

    /// Number of chapters renamed.
    pub fn chapters_renamed(&self) -> usize {
        self.renamed.len()
    }
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
/// Detailed results about all processing operations.
pub fn process_chapters(
    data: &mut ChapterData,
    deduplicate: bool,
    normalize_ends: bool,
    rename: bool,
) -> ProcessingStats {
    let mut stats = ProcessingStats::default();

    // Always deduplicate before other operations
    if deduplicate {
        stats.duplicates = deduplicate_chapters(data);
    }

    // Normalize ends after deduplication
    if normalize_ends {
        stats.normalized = normalize_chapter_ends(data);
    }

    // Rename last (so numbering is correct after deduplication)
    if rename {
        stats.renamed = rename_chapters(data);
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
        assert_eq!(removed.len(), 1);
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
        let normalized = normalize_chapter_ends(&mut data);

        // All 3 chapters should be normalized (they had no end times)
        assert_eq!(normalized.len(), 3);

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
        let renamed = rename_chapters(&mut data);

        assert_eq!(renamed.len(), 3);
        assert_eq!(data.chapters[0].display_name(), Some("Chapter 01"));
        assert_eq!(data.chapters[1].display_name(), Some("Chapter 02"));
        assert_eq!(data.chapters[2].display_name(), Some("Chapter 03"));
    }

    #[test]
    fn test_process_all() {
        let mut data = create_test_chapters();
        data.add_chapter(ChapterEntry::new(0).with_name("Duplicate", "eng"));

        let stats = process_chapters(&mut data, true, true, true);

        assert_eq!(stats.duplicates_removed(), 1);
        assert!(stats.ends_normalized() > 0);
        assert!(stats.chapters_renamed() > 0);
        assert_eq!(data.len(), 3);
    }
}
