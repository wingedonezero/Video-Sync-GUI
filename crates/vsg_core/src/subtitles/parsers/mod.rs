//! Subtitle parsers for various formats.
//!
//! Each parser is a pure function that takes content and returns `SubtitleData`.

mod ass;
mod srt;

pub use ass::{parse_ass, parse_ass_time};
pub use srt::{parse_srt, parse_srt_time};

use crate::subtitles::error::ParseError;
use crate::subtitles::types::{SubtitleData, SubtitleFormat};

/// Parse subtitle content with auto-detection.
///
/// Tries to detect the format from content if not specified.
pub fn parse_content(content: &str, format: Option<SubtitleFormat>) -> Result<SubtitleData, ParseError> {
    let format = format.unwrap_or_else(|| detect_format(content));

    match format {
        SubtitleFormat::Ass => parse_ass(content),
        SubtitleFormat::Srt | SubtitleFormat::WebVtt => parse_srt(content),
    }
}

/// Detect subtitle format from content.
fn detect_format(content: &str) -> SubtitleFormat {
    let content_lower = content.to_lowercase();

    // ASS/SSA detection
    if content_lower.contains("[script info]")
        || content_lower.contains("[v4+ styles]")
        || content_lower.contains("[v4 styles]")
        || content_lower.contains("[events]")
    {
        return SubtitleFormat::Ass;
    }

    // WebVTT detection
    if content.trim().starts_with("WEBVTT") {
        return SubtitleFormat::WebVtt;
    }

    // Default to SRT
    SubtitleFormat::Srt
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detect_format_ass() {
        let content = "[Script Info]\nTitle: Test\n";
        assert_eq!(detect_format(content), SubtitleFormat::Ass);
    }

    #[test]
    fn test_detect_format_srt() {
        let content = "1\n00:00:01,000 --> 00:00:04,000\nHello\n";
        assert_eq!(detect_format(content), SubtitleFormat::Srt);
    }

    #[test]
    fn test_detect_format_webvtt() {
        let content = "WEBVTT\n\n00:00:01.000 --> 00:00:04.000\nHello\n";
        assert_eq!(detect_format(content), SubtitleFormat::WebVtt);
    }
}
