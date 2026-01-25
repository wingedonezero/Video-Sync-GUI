//! Chapter data types.
//!
//! Matroska chapter format reference:
//! https://www.matroska.org/technical/chapters.html

use serde::{Deserialize, Serialize};

/// Error type for chapter operations.
#[derive(Debug, Clone)]
pub enum ChapterError {
    /// No chapters found in the file.
    NoChapters,
    /// Failed to execute external tool.
    ToolExecutionFailed { tool: String, message: String },
    /// Failed to parse chapter XML.
    ParseError(String),
    /// Failed to write chapter file.
    WriteError(String),
    /// I/O error.
    IoError(String),
}

impl std::fmt::Display for ChapterError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            ChapterError::NoChapters => write!(f, "No chapters found"),
            ChapterError::ToolExecutionFailed { tool, message } => {
                write!(f, "{} execution failed: {}", tool, message)
            }
            ChapterError::ParseError(msg) => write!(f, "Chapter parse error: {}", msg),
            ChapterError::WriteError(msg) => write!(f, "Chapter write error: {}", msg),
            ChapterError::IoError(msg) => write!(f, "I/O error: {}", msg),
        }
    }
}

impl std::error::Error for ChapterError {}

/// Language information for a chapter display.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ChapterLanguage {
    /// ISO 639-2 three-letter code (e.g., "eng", "jpn").
    pub iso639_2: String,
    /// IETF BCP 47 language tag (e.g., "en", "ja").
    pub ietf: Option<String>,
}

impl ChapterLanguage {
    /// Create a new chapter language with ISO 639-2 code.
    pub fn new(iso639_2: impl Into<String>) -> Self {
        let code: String = iso639_2.into();
        let ietf = Self::iso639_2_to_ietf(&code);
        Self {
            iso639_2: code,
            ietf,
        }
    }

    /// Create with both ISO and IETF codes.
    pub fn with_ietf(iso639_2: impl Into<String>, ietf: impl Into<String>) -> Self {
        Self {
            iso639_2: iso639_2.into(),
            ietf: Some(ietf.into()),
        }
    }

    /// Default "undefined" language.
    pub fn undefined() -> Self {
        Self {
            iso639_2: "und".to_string(),
            ietf: Some("und".to_string()),
        }
    }

    /// Convert ISO 639-2 code to IETF BCP 47.
    fn iso639_2_to_ietf(code: &str) -> Option<String> {
        match code.to_lowercase().as_str() {
            "eng" => Some("en".to_string()),
            "jpn" => Some("ja".to_string()),
            "spa" => Some("es".to_string()),
            "fra" | "fre" => Some("fr".to_string()),
            "deu" | "ger" => Some("de".to_string()),
            "ita" => Some("it".to_string()),
            "por" => Some("pt".to_string()),
            "rus" => Some("ru".to_string()),
            "kor" => Some("ko".to_string()),
            "zho" | "chi" => Some("zh".to_string()),
            "und" => Some("und".to_string()),
            _ => None,
        }
    }
}

/// A chapter display entry (name in a specific language).
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChapterDisplay {
    /// Chapter name/title.
    pub name: String,
    /// Language information.
    pub language: ChapterLanguage,
}

impl ChapterDisplay {
    /// Create a new chapter display.
    pub fn new(name: impl Into<String>, language: ChapterLanguage) -> Self {
        Self {
            name: name.into(),
            language,
        }
    }

    /// Create with just a name (undefined language).
    pub fn with_name(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            language: ChapterLanguage::undefined(),
        }
    }
}

/// A single chapter entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Chapter {
    /// Unique chapter ID (optional in Matroska).
    pub uid: Option<u64>,

    /// Chapter start time in nanoseconds.
    pub start_ns: i64,

    /// Chapter end time in nanoseconds (optional, derived from next chapter if missing).
    pub end_ns: Option<i64>,

    /// Display entries (chapter name in different languages).
    /// At least one entry should exist.
    pub displays: Vec<ChapterDisplay>,

    /// Whether this chapter is hidden.
    pub hidden: bool,

    /// Whether this chapter is enabled.
    pub enabled: bool,
}

impl Chapter {
    /// Create a new chapter with start time and name.
    pub fn new(start_ns: i64, name: impl Into<String>) -> Self {
        Self {
            uid: None,
            start_ns,
            end_ns: None,
            displays: vec![ChapterDisplay::with_name(name)],
            hidden: false,
            enabled: true,
        }
    }

    /// Create with explicit start and end times.
    pub fn with_times(start_ns: i64, end_ns: i64, name: impl Into<String>) -> Self {
        Self {
            uid: None,
            start_ns,
            end_ns: Some(end_ns),
            displays: vec![ChapterDisplay::with_name(name)],
            hidden: false,
            enabled: true,
        }
    }

    /// Get the primary name (first display entry).
    pub fn name(&self) -> &str {
        self.displays
            .first()
            .map(|d| d.name.as_str())
            .unwrap_or("Unnamed Chapter")
    }

    /// Get start time in milliseconds.
    pub fn start_ms(&self) -> i64 {
        self.start_ns / 1_000_000
    }

    /// Get end time in milliseconds (if set).
    pub fn end_ms(&self) -> Option<i64> {
        self.end_ns.map(|ns| ns / 1_000_000)
    }
}

/// A list of chapters.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ChapterList {
    /// The chapters, should be sorted by start time.
    pub chapters: Vec<Chapter>,
}

impl ChapterList {
    /// Create a new empty chapter list.
    pub fn new() -> Self {
        Self::default()
    }

    /// Create from a vector of chapters.
    pub fn from_chapters(chapters: Vec<Chapter>) -> Self {
        let mut list = Self { chapters };
        list.sort();
        list
    }

    /// Number of chapters.
    pub fn len(&self) -> usize {
        self.chapters.len()
    }

    /// Check if empty.
    pub fn is_empty(&self) -> bool {
        self.chapters.is_empty()
    }

    /// Add a chapter.
    pub fn push(&mut self, chapter: Chapter) {
        self.chapters.push(chapter);
    }

    /// Sort chapters by start time.
    pub fn sort(&mut self) {
        self.chapters.sort_by_key(|c| c.start_ns);
    }

    /// Get iterator over chapters.
    pub fn iter(&self) -> impl Iterator<Item = &Chapter> {
        self.chapters.iter()
    }

    /// Get mutable iterator over chapters.
    pub fn iter_mut(&mut self) -> impl Iterator<Item = &mut Chapter> {
        self.chapters.iter_mut()
    }
}

/// Parse a Matroska timestamp string to nanoseconds.
///
/// Format: HH:MM:SS.nnnnnnnnn
pub fn parse_timestamp(s: &str) -> Result<i64, ChapterError> {
    let s = s.trim();
    let parts: Vec<&str> = s.split(':').collect();

    if parts.len() != 3 {
        return Err(ChapterError::ParseError(format!(
            "Invalid timestamp format: {}",
            s
        )));
    }

    let hours: i64 = parts[0]
        .parse()
        .map_err(|_| ChapterError::ParseError(format!("Invalid hours: {}", parts[0])))?;

    let minutes: i64 = parts[1]
        .parse()
        .map_err(|_| ChapterError::ParseError(format!("Invalid minutes: {}", parts[1])))?;

    // Split seconds and fractional part
    let sec_parts: Vec<&str> = parts[2].split('.').collect();
    let seconds: i64 = sec_parts[0]
        .parse()
        .map_err(|_| ChapterError::ParseError(format!("Invalid seconds: {}", sec_parts[0])))?;

    // Parse fractional nanoseconds (pad to 9 digits)
    let frac_ns: i64 = if sec_parts.len() > 1 {
        let frac = sec_parts[1];
        let padded = format!("{:0<9}", frac);
        padded[..9]
            .parse()
            .map_err(|_| ChapterError::ParseError(format!("Invalid nanoseconds: {}", frac)))?
    } else {
        0
    };

    let total_ns = (hours * 3600 + minutes * 60 + seconds) * 1_000_000_000 + frac_ns;
    Ok(total_ns)
}

/// Format nanoseconds as a Matroska timestamp string.
///
/// Format: HH:MM:SS.nnnnnnnnn
pub fn format_timestamp(ns: i64) -> String {
    let ns = ns.max(0);
    let frac = ns % 1_000_000_000;
    let total_s = ns / 1_000_000_000;
    let hours = total_s / 3600;
    let minutes = (total_s % 3600) / 60;
    let seconds = total_s % 60;
    format!("{:02}:{:02}:{:02}.{:09}", hours, minutes, seconds, frac)
}

/// Format nanoseconds for human-readable logging.
///
/// Format: HH:MM:SS.mmm (millisecond precision)
pub fn format_timestamp_readable(ns: i64) -> String {
    let ns = ns.max(0);
    let total_ms = ns / 1_000_000;
    let ms = total_ms % 1000;
    let total_s = total_ms / 1000;
    let hours = total_s / 3600;
    let minutes = (total_s % 3600) / 60;
    let seconds = total_s % 60;
    format!("{:02}:{:02}:{:02}.{:03}", hours, minutes, seconds, ms)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_timestamp() {
        // Standard format
        assert_eq!(parse_timestamp("00:01:30.000000000").unwrap(), 90_000_000_000);
        // With fractional seconds
        assert_eq!(parse_timestamp("00:00:01.500000000").unwrap(), 1_500_000_000);
        // Short fraction (should be padded): "1.5" = 1.5 seconds = 1,500,000,000 ns
        assert_eq!(parse_timestamp("00:00:01.5").unwrap(), 1_500_000_000);
        // Zero
        assert_eq!(parse_timestamp("00:00:00.000000000").unwrap(), 0);
    }

    #[test]
    fn test_format_timestamp() {
        assert_eq!(format_timestamp(90_000_000_000), "00:01:30.000000000");
        assert_eq!(format_timestamp(1_500_000_000), "00:00:01.500000000");
        assert_eq!(format_timestamp(0), "00:00:00.000000000");
        // Negative clamped to 0
        assert_eq!(format_timestamp(-1000), "00:00:00.000000000");
    }

    #[test]
    fn test_roundtrip() {
        let ns = 91_316_666_000i64; // 00:01:31.316666000
        let formatted = format_timestamp(ns);
        let parsed = parse_timestamp(&formatted).unwrap();
        assert_eq!(parsed, ns);
    }

    #[test]
    fn test_chapter_language() {
        let lang = ChapterLanguage::new("eng");
        assert_eq!(lang.iso639_2, "eng");
        assert_eq!(lang.ietf, Some("en".to_string()));

        let lang = ChapterLanguage::new("unknown");
        assert_eq!(lang.ietf, None);
    }

    #[test]
    fn test_chapter_list_sort() {
        let mut list = ChapterList::new();
        list.push(Chapter::new(200_000_000, "Chapter 2"));
        list.push(Chapter::new(100_000_000, "Chapter 1"));
        list.push(Chapter::new(300_000_000, "Chapter 3"));

        list.sort();

        assert_eq!(list.chapters[0].name(), "Chapter 1");
        assert_eq!(list.chapters[1].name(), "Chapter 2");
        assert_eq!(list.chapters[2].name(), "Chapter 3");
    }
}
