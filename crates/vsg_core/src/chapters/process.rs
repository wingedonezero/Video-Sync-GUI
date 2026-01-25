//! Chapter processing operations.
//!
//! This module provides functions for modifying chapters:
//! - Time shifting (to match global sync offset)
//! - Normalization (fix end times, remove duplicates)
//! - Renaming (sequential chapter names)

use super::types::{
    ChapterDisplay, ChapterError, ChapterLanguage, ChapterList,
    format_timestamp, format_timestamp_readable,
};

/// Configuration for chapter processing.
#[derive(Debug, Clone)]
pub struct ChapterProcessConfig {
    /// Rename chapters to "Chapter 01", "Chapter 02", etc.
    pub rename: bool,
    /// Snap chapters to keyframes (future feature).
    pub snap_enabled: bool,
    /// Snap mode: "previous" or "nearest".
    pub snap_mode: String,
    /// Snap threshold in milliseconds.
    pub snap_threshold_ms: u32,
    /// Only snap chapter starts (not ends).
    pub snap_starts_only: bool,
}

impl Default for ChapterProcessConfig {
    fn default() -> Self {
        Self {
            rename: false,
            snap_enabled: false,
            snap_mode: "previous".to_string(),
            snap_threshold_ms: 250,
            snap_starts_only: true,
        }
    }
}

impl ChapterList {
    /// Shift all chapter timestamps by the given milliseconds.
    ///
    /// This is used to apply the global sync offset to chapters so they
    /// remain aligned with the shifted video timeline.
    ///
    /// # Arguments
    ///
    /// * `shift_ms` - Milliseconds to shift (positive = later, negative = earlier)
    ///
    /// # Note
    ///
    /// Timestamps are clamped to 0 (negative results become 0).
    pub fn shift(&mut self, shift_ms: i64) {
        let shift_ns = shift_ms * 1_000_000;

        for chapter in &mut self.chapters {
            chapter.start_ns = (chapter.start_ns + shift_ns).max(0);
            if let Some(ref mut end_ns) = chapter.end_ns {
                *end_ns = (*end_ns + shift_ns).max(0);
            }
        }
    }

    /// Normalize chapters: sort, remove duplicates, fix end times.
    ///
    /// Operations performed:
    /// 1. Sort by start time
    /// 2. Remove duplicate chapters (same start time within 100ms)
    /// 3. Set end times to next chapter's start (or +1s for last chapter)
    ///
    /// # Returns
    ///
    /// A log of changes made, useful for debugging.
    pub fn normalize(&mut self) -> Vec<String> {
        let mut log = Vec::new();

        // 1. Sort by start time
        self.sort();

        // 2. Remove duplicates (same start time within 100ms tolerance)
        let original_count = self.chapters.len();
        let mut seen_starts: Vec<i64> = Vec::new();
        let mut to_remove: Vec<usize> = Vec::new();

        for (i, chapter) in self.chapters.iter().enumerate() {
            let dominated = seen_starts
                .iter()
                .any(|&s| (chapter.start_ns - s).abs() < 100_000_000);

            if dominated {
                log.push(format!(
                    "Removed duplicate chapter '{}' at {}",
                    chapter.name(),
                    format_timestamp_readable(chapter.start_ns)
                ));
                to_remove.push(i);
            } else {
                seen_starts.push(chapter.start_ns);
            }
        }

        // Remove in reverse order to preserve indices
        for i in to_remove.into_iter().rev() {
            self.chapters.remove(i);
        }

        if self.chapters.len() < original_count {
            log.push(format!(
                "Removed {} duplicate chapters",
                original_count - self.chapters.len()
            ));
        }

        // 3. Fix end times
        let len = self.chapters.len();
        for i in 0..len {
            let current_start = self.chapters[i].start_ns;
            let original_end = self.chapters[i].end_ns;

            // Calculate desired end time
            let desired_end = if i + 1 < len {
                // End at next chapter's start (seamless chapters)
                self.chapters[i + 1].start_ns
            } else {
                // Last chapter: use original end or add 1 second
                original_end.unwrap_or(current_start + 1_000_000_000)
                    .max(current_start + 1_000_000_000)
            };

            // Update if different
            if self.chapters[i].end_ns != Some(desired_end) {
                let old_end_str = original_end
                    .map(|ns| format_timestamp_readable(ns))
                    .unwrap_or_else(|| "None".to_string());

                log.push(format!(
                    "Normalized '{}' end time: {} -> {}",
                    self.chapters[i].name(),
                    old_end_str,
                    format_timestamp_readable(desired_end)
                ));

                self.chapters[i].end_ns = Some(desired_end);
            }
        }

        log
    }

    /// Rename chapters to sequential names ("Chapter 01", "Chapter 02", etc.).
    ///
    /// Preserves language information from the original displays.
    ///
    /// # Returns
    ///
    /// A log of renames performed.
    pub fn rename_sequential(&mut self) -> Vec<String> {
        let mut log = Vec::new();

        for (i, chapter) in self.chapters.iter_mut().enumerate() {
            let new_name = format!("Chapter {:02}", i + 1);
            let old_name = chapter.name().to_string();

            // Preserve language from first display, or use default
            let language = chapter
                .displays
                .first()
                .map(|d| d.language.clone())
                .unwrap_or_else(ChapterLanguage::undefined);

            // Replace all displays with a single renamed one
            chapter.displays = vec![ChapterDisplay::new(&new_name, language.clone())];

            log.push(format!(
                "Renamed '{}' -> '{}' (lang: {})",
                old_name, new_name, language.iso639_2
            ));
        }

        log
    }

    /// Serialize chapters to Matroska chapter XML format.
    pub fn to_xml(&self) -> String {
        let mut xml = String::new();
        xml.push_str("<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n");
        xml.push_str("<!DOCTYPE Chapters SYSTEM \"matroskachapters.dtd\">\n");
        xml.push_str("<Chapters>\n");
        xml.push_str("  <EditionEntry>\n");

        for chapter in &self.chapters {
            xml.push_str("    <ChapterAtom>\n");

            // UID (optional)
            if let Some(uid) = chapter.uid {
                xml.push_str(&format!("      <ChapterUID>{}</ChapterUID>\n", uid));
            }

            // Times
            xml.push_str(&format!(
                "      <ChapterTimeStart>{}</ChapterTimeStart>\n",
                format_timestamp(chapter.start_ns)
            ));
            if let Some(end_ns) = chapter.end_ns {
                xml.push_str(&format!(
                    "      <ChapterTimeEnd>{}</ChapterTimeEnd>\n",
                    format_timestamp(end_ns)
                ));
            }

            // Flags
            if chapter.hidden {
                xml.push_str("      <ChapterFlagHidden>1</ChapterFlagHidden>\n");
            }
            if !chapter.enabled {
                xml.push_str("      <ChapterFlagEnabled>0</ChapterFlagEnabled>\n");
            }

            // Displays
            for display in &chapter.displays {
                xml.push_str("      <ChapterDisplay>\n");
                xml.push_str(&format!(
                    "        <ChapterString>{}</ChapterString>\n",
                    escape_xml(&display.name)
                ));
                xml.push_str(&format!(
                    "        <ChapterLanguage>{}</ChapterLanguage>\n",
                    display.language.iso639_2
                ));
                if let Some(ref ietf) = display.language.ietf {
                    xml.push_str(&format!(
                        "        <ChapLanguageIETF>{}</ChapLanguageIETF>\n",
                        ietf
                    ));
                }
                xml.push_str("      </ChapterDisplay>\n");
            }

            xml.push_str("    </ChapterAtom>\n");
        }

        xml.push_str("  </EditionEntry>\n");
        xml.push_str("</Chapters>\n");

        xml
    }
}

/// Escape special XML characters.
fn escape_xml(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

/// Process chapters with the given configuration.
///
/// This is the main entry point for chapter processing. It applies:
/// 1. Time shift (if shift_ms != 0)
/// 2. Normalization (always)
/// 3. Renaming (if enabled)
///
/// # Arguments
///
/// * `chapters` - The chapter list to process (modified in place)
/// * `shift_ms` - Milliseconds to shift all timestamps
/// * `config` - Processing configuration
///
/// # Returns
///
/// A log of all changes made.
pub fn process_chapters(
    chapters: &mut ChapterList,
    shift_ms: i64,
    config: &ChapterProcessConfig,
) -> Vec<String> {
    let mut log = Vec::new();

    // 1. Shift timestamps
    if shift_ms != 0 {
        log.push(format!("Shifting all timestamps by +{} ms", shift_ms));
        chapters.shift(shift_ms);
    }

    // 2. Normalize
    log.push("Normalizing chapter data...".to_string());
    let norm_log = chapters.normalize();
    log.extend(norm_log);

    // 3. Rename if enabled
    if config.rename {
        log.push("Renaming chapters to sequential names...".to_string());
        let rename_log = chapters.rename_sequential();
        log.extend(rename_log);
    }

    // TODO: Keyframe snapping (requires video analysis)
    if config.snap_enabled {
        log.push("Keyframe snapping not yet implemented".to_string());
    }

    log
}

/// Write chapter list to an XML file.
pub fn write_chapters_xml(
    chapters: &ChapterList,
    output_path: &std::path::Path,
) -> Result<(), ChapterError> {
    let xml = chapters.to_xml();

    // Create parent directory if needed
    if let Some(parent) = output_path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| {
            ChapterError::IoError(format!("Failed to create directory: {}", e))
        })?;
    }

    std::fs::write(output_path, xml).map_err(|e| {
        ChapterError::WriteError(format!("Failed to write chapters: {}", e))
    })?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::types::Chapter;

    fn create_test_chapters() -> ChapterList {
        let mut list = ChapterList::new();
        list.push(Chapter::new(0, "Opening"));
        list.push(Chapter::new(300_000_000_000, "Part A")); // 5 min
        list.push(Chapter::new(600_000_000_000, "Part B")); // 10 min
        list
    }

    #[test]
    fn test_shift() {
        let mut chapters = create_test_chapters();
        chapters.shift(1000); // +1 second

        assert_eq!(chapters.chapters[0].start_ns, 1_000_000_000);
        assert_eq!(chapters.chapters[1].start_ns, 301_000_000_000);
    }

    #[test]
    fn test_shift_negative_clamped() {
        let mut chapters = create_test_chapters();
        chapters.shift(-1000); // -1 second, but first chapter at 0

        // First chapter clamped to 0
        assert_eq!(chapters.chapters[0].start_ns, 0);
        // Others shifted normally
        assert_eq!(chapters.chapters[1].start_ns, 299_000_000_000);
    }

    #[test]
    fn test_normalize_end_times() {
        let mut chapters = create_test_chapters();
        chapters.normalize();

        // End times should be set to next chapter's start
        assert_eq!(chapters.chapters[0].end_ns, Some(300_000_000_000));
        assert_eq!(chapters.chapters[1].end_ns, Some(600_000_000_000));
        // Last chapter gets +1s
        assert!(chapters.chapters[2].end_ns.unwrap() > 600_000_000_000);
    }

    #[test]
    fn test_normalize_removes_duplicates() {
        let mut chapters = ChapterList::new();
        chapters.push(Chapter::new(0, "Chapter 1"));
        chapters.push(Chapter::new(50_000_000, "Chapter 1 Duplicate")); // 50ms later - duplicate
        chapters.push(Chapter::new(300_000_000_000, "Chapter 2"));

        chapters.normalize();

        assert_eq!(chapters.len(), 2);
        assert_eq!(chapters.chapters[0].name(), "Chapter 1");
        assert_eq!(chapters.chapters[1].name(), "Chapter 2");
    }

    #[test]
    fn test_rename_sequential() {
        let mut chapters = create_test_chapters();
        chapters.rename_sequential();

        assert_eq!(chapters.chapters[0].name(), "Chapter 01");
        assert_eq!(chapters.chapters[1].name(), "Chapter 02");
        assert_eq!(chapters.chapters[2].name(), "Chapter 03");
    }

    #[test]
    fn test_to_xml_roundtrip() {
        let mut chapters = create_test_chapters();
        chapters.normalize();

        let xml = chapters.to_xml();

        assert!(xml.contains("<ChapterTimeStart>00:00:00.000000000</ChapterTimeStart>"));
        assert!(xml.contains("<ChapterString>Opening</ChapterString>"));
        assert!(xml.contains("<!DOCTYPE Chapters"));
    }

    #[test]
    fn test_escape_xml() {
        assert_eq!(escape_xml("Hello & World"), "Hello &amp; World");
        assert_eq!(escape_xml("<test>"), "&lt;test&gt;");
    }
}
