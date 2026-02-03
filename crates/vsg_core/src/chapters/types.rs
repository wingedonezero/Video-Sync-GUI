//! Chapter types and error definitions.
//!
//! Provides types for representing Matroska chapter data and
//! errors that can occur during chapter operations.

use serde::{Deserialize, Serialize};

/// A single chapter entry with timing and metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChapterEntry {
    /// Chapter start time in nanoseconds.
    pub start_ns: u64,
    /// Chapter end time in nanoseconds (optional).
    pub end_ns: Option<u64>,
    /// Chapter display names by language (e.g., "eng" -> "Chapter 1").
    pub names: Vec<ChapterName>,
    /// Unique identifier within the chapter atom.
    pub uid: Option<u64>,
    /// Whether this chapter is hidden.
    pub hidden: bool,
    /// Whether this chapter is enabled.
    pub enabled: bool,
}

impl ChapterEntry {
    /// Create a new chapter entry with the given start time.
    pub fn new(start_ns: u64) -> Self {
        Self {
            start_ns,
            end_ns: None,
            names: Vec::new(),
            uid: None,
            hidden: false,
            enabled: true,
        }
    }

    /// Set the end time.
    pub fn with_end(mut self, end_ns: u64) -> Self {
        self.end_ns = Some(end_ns);
        self
    }

    /// Add a name for this chapter.
    pub fn with_name(mut self, name: impl Into<String>, language: impl Into<String>) -> Self {
        self.names.push(ChapterName {
            name: name.into(),
            language: language.into(),
            language_ietf: None,
        });
        self
    }

    /// Add a name for this chapter with both legacy and IETF language codes.
    pub fn with_name_ietf(
        mut self,
        name: impl Into<String>,
        language: impl Into<String>,
        language_ietf: impl Into<String>,
    ) -> Self {
        self.names.push(ChapterName {
            name: name.into(),
            language: language.into(),
            language_ietf: Some(language_ietf.into()),
        });
        self
    }

    /// Get the start time in milliseconds.
    pub fn start_ms(&self) -> i64 {
        (self.start_ns / 1_000_000) as i64
    }

    /// Get the start time in seconds.
    pub fn start_secs(&self) -> f64 {
        self.start_ns as f64 / 1_000_000_000.0
    }

    /// Get the end time in milliseconds (if set).
    pub fn end_ms(&self) -> Option<i64> {
        self.end_ns.map(|ns| (ns / 1_000_000) as i64)
    }

    /// Get the primary display name (first name in list).
    pub fn display_name(&self) -> Option<&str> {
        self.names.first().map(|n| n.name.as_str())
    }

    /// Format start time as HH:MM:SS.nnnnnnnnn for XML output.
    pub fn format_start_time(&self) -> String {
        format_timestamp_ns(self.start_ns)
    }

    /// Format end time as HH:MM:SS.nnnnnnnnn for XML output.
    pub fn format_end_time(&self) -> Option<String> {
        self.end_ns.map(format_timestamp_ns)
    }
}

/// A chapter name with its language.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChapterName {
    /// Display name.
    pub name: String,
    /// Legacy language code (ISO 639-2, e.g., "eng", "jpn").
    /// This is written as `ChapterLanguage` in the XML.
    pub language: String,
    /// Modern IETF language code (BCP 47, e.g., "en", "ja").
    /// This is written as `ChapLanguageIETF` in the XML.
    /// If None, will be derived from `language` when serializing.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub language_ietf: Option<String>,
}

/// A collection of chapters (chapter atom in Matroska).
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ChapterData {
    /// List of chapter entries.
    pub chapters: Vec<ChapterEntry>,
    /// Edition UID (optional).
    pub edition_uid: Option<u64>,
    /// Whether this edition is the default.
    pub edition_default: bool,
    /// Whether this edition is hidden.
    pub edition_hidden: bool,
}

impl ChapterData {
    /// Create a new empty chapter data.
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a chapter entry.
    pub fn add_chapter(&mut self, chapter: ChapterEntry) {
        self.chapters.push(chapter);
    }

    /// Get the number of chapters.
    pub fn len(&self) -> usize {
        self.chapters.len()
    }

    /// Check if there are no chapters.
    pub fn is_empty(&self) -> bool {
        self.chapters.is_empty()
    }

    /// Sort chapters by start time.
    pub fn sort_by_time(&mut self) {
        self.chapters.sort_by_key(|c| c.start_ns);
    }

    /// Get an iterator over chapters.
    pub fn iter(&self) -> impl Iterator<Item = &ChapterEntry> {
        self.chapters.iter()
    }

    /// Get a mutable iterator over chapters.
    pub fn iter_mut(&mut self) -> impl Iterator<Item = &mut ChapterEntry> {
        self.chapters.iter_mut()
    }
}

/// Keyframe information for chapter snapping.
#[derive(Debug, Clone)]
pub struct KeyframeInfo {
    /// Keyframe timestamps in nanoseconds, sorted.
    pub timestamps_ns: Vec<u64>,
}

impl KeyframeInfo {
    /// Create new keyframe info from timestamps.
    pub fn new(timestamps_ns: Vec<u64>) -> Self {
        let mut sorted = timestamps_ns;
        sorted.sort();
        Self {
            timestamps_ns: sorted,
        }
    }

    /// Find the nearest keyframe to the given timestamp.
    pub fn nearest(&self, timestamp_ns: u64) -> Option<u64> {
        if self.timestamps_ns.is_empty() {
            return None;
        }

        // Binary search for the closest keyframe
        match self.timestamps_ns.binary_search(&timestamp_ns) {
            Ok(idx) => Some(self.timestamps_ns[idx]),
            Err(idx) => {
                if idx == 0 {
                    Some(self.timestamps_ns[0])
                } else if idx >= self.timestamps_ns.len() {
                    Some(*self.timestamps_ns.last().unwrap())
                } else {
                    // Check which is closer: idx-1 or idx
                    let before = self.timestamps_ns[idx - 1];
                    let after = self.timestamps_ns[idx];
                    let dist_before = timestamp_ns.saturating_sub(before);
                    let dist_after = after.saturating_sub(timestamp_ns);
                    if dist_before <= dist_after {
                        Some(before)
                    } else {
                        Some(after)
                    }
                }
            }
        }
    }

    /// Find the previous keyframe at or before the given timestamp.
    pub fn previous(&self, timestamp_ns: u64) -> Option<u64> {
        if self.timestamps_ns.is_empty() {
            return None;
        }

        match self.timestamps_ns.binary_search(&timestamp_ns) {
            Ok(idx) => Some(self.timestamps_ns[idx]),
            Err(idx) => {
                if idx == 0 {
                    None // No keyframe before this timestamp
                } else {
                    Some(self.timestamps_ns[idx - 1])
                }
            }
        }
    }

    /// Find the next keyframe at or after the given timestamp.
    pub fn next(&self, timestamp_ns: u64) -> Option<u64> {
        if self.timestamps_ns.is_empty() {
            return None;
        }

        match self.timestamps_ns.binary_search(&timestamp_ns) {
            Ok(idx) => Some(self.timestamps_ns[idx]),
            Err(idx) => {
                if idx >= self.timestamps_ns.len() {
                    None // No keyframe after this timestamp
                } else {
                    Some(self.timestamps_ns[idx])
                }
            }
        }
    }
}

/// Error types for chapter operations.
#[derive(Debug, thiserror::Error)]
pub enum ChapterError {
    /// Chapter extraction failed.
    #[error("Chapter extraction failed: {0}")]
    ExtractionError(String),

    /// Chapter parsing failed.
    #[error("Failed to parse chapters: {0}")]
    ParseError(String),

    /// Chapter XML is malformed.
    #[error("Malformed chapter XML: {0}")]
    MalformedXml(String),

    /// No chapters found in source.
    #[error("No chapters found in source")]
    NoChapters,

    /// Keyframe extraction failed.
    #[error("Failed to extract keyframes: {0}")]
    KeyframeError(String),

    /// IO error.
    #[error("IO error: {0}")]
    IoError(#[from] std::io::Error),

    /// Command execution failed.
    #[error("{tool} failed with exit code {exit_code}: {message}")]
    CommandFailed {
        tool: String,
        exit_code: i32,
        message: String,
    },
}

/// Type alias for chapter operation results.
pub type ChapterResult<T> = Result<T, ChapterError>;

/// Format a nanosecond timestamp as HH:MM:SS.nnnnnnnnn.
pub fn format_timestamp_ns(ns: u64) -> String {
    let total_secs = ns / 1_000_000_000;
    let remaining_ns = ns % 1_000_000_000;

    let hours = total_secs / 3600;
    let minutes = (total_secs % 3600) / 60;
    let seconds = total_secs % 60;

    format!(
        "{:02}:{:02}:{:02}.{:09}",
        hours, minutes, seconds, remaining_ns
    )
}

/// Parse a timestamp string (HH:MM:SS.nnnnnnnnn) to nanoseconds.
pub fn parse_timestamp_ns(time_str: &str) -> Option<u64> {
    let parts: Vec<&str> = time_str.split(':').collect();
    if parts.len() != 3 {
        return None;
    }

    let hours: u64 = parts[0].parse().ok()?;
    let minutes: u64 = parts[1].parse().ok()?;

    let sec_parts: Vec<&str> = parts[2].split('.').collect();
    let seconds: u64 = sec_parts[0].parse().ok()?;
    let nanos: u64 = if sec_parts.len() > 1 {
        // Pad or truncate to 9 digits
        let nano_str = format!("{:0<9}", sec_parts[1]);
        nano_str[..9.min(nano_str.len())].parse().unwrap_or(0)
    } else {
        0
    };

    let total_ns = (hours * 3600 + minutes * 60 + seconds) * 1_000_000_000 + nanos;
    Some(total_ns)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn format_timestamp_works() {
        assert_eq!(format_timestamp_ns(0), "00:00:00.000000000");
        assert_eq!(format_timestamp_ns(1_500_000_000), "00:00:01.500000000");
        assert_eq!(format_timestamp_ns(3661_000_000_000), "01:01:01.000000000");
    }

    #[test]
    fn parse_timestamp_works() {
        assert_eq!(parse_timestamp_ns("00:00:00.000000000"), Some(0));
        assert_eq!(
            parse_timestamp_ns("00:00:01.500000000"),
            Some(1_500_000_000)
        );
        assert_eq!(
            parse_timestamp_ns("01:01:01.000000000"),
            Some(3661_000_000_000)
        );
    }

    #[test]
    fn timestamp_roundtrip() {
        let original = 12345_678_901_234u64;
        let formatted = format_timestamp_ns(original);
        let parsed = parse_timestamp_ns(&formatted).unwrap();
        assert_eq!(original, parsed);
    }

    #[test]
    fn keyframe_nearest_works() {
        let kf = KeyframeInfo::new(vec![0, 1000, 2000, 3000]);
        assert_eq!(kf.nearest(500), Some(0));
        assert_eq!(kf.nearest(600), Some(1000));
        assert_eq!(kf.nearest(1000), Some(1000));
        assert_eq!(kf.nearest(2500), Some(2000));
        assert_eq!(kf.nearest(2600), Some(3000));
    }

    #[test]
    fn keyframe_previous_works() {
        let kf = KeyframeInfo::new(vec![0, 1000, 2000, 3000]);
        assert_eq!(kf.previous(500), Some(0));
        assert_eq!(kf.previous(1000), Some(1000));
        assert_eq!(kf.previous(1500), Some(1000));
        assert_eq!(kf.previous(0), Some(0));
    }

    #[test]
    fn chapter_entry_times() {
        let chapter = ChapterEntry::new(1_500_000_000);
        assert_eq!(chapter.start_ms(), 1500);
        assert!((chapter.start_secs() - 1.5).abs() < 0.001);
    }
}
