//! SRT subtitle parser.
//!
//! Parses SubRip (.srt) subtitle files.
//!
//! # Format Overview
//!
//! SRT files consist of sequential entries:
//! ```text
//! 1
//! 00:00:01,000 --> 00:00:04,000
//! Hello, world!
//!
//! 2
//! 00:00:05,000 --> 00:00:08,000
//! This is a test.
//! ```
//!
//! Each entry has:
//! - Index number (ignored during parsing, regenerated on write)
//! - Timing line: `HH:MM:SS,mmm --> HH:MM:SS,mmm`
//! - One or more lines of text
//! - Blank line separator

use crate::subtitles::error::ParseError;
use crate::subtitles::types::{SubtitleData, SubtitleEvent, SubtitleFormat};

/// Parse SRT content into SubtitleData.
///
/// # Arguments
/// * `content` - The raw SRT file content as a string.
///
/// # Returns
/// * `Ok(SubtitleData)` - Parsed subtitle data.
/// * `Err(ParseError)` - If parsing fails.
pub fn parse_srt(content: &str) -> Result<SubtitleData, ParseError> {
    let mut data = SubtitleData::with_format(SubtitleFormat::Srt);

    // Normalize line endings and split into blocks
    let content = content.replace("\r\n", "\n").replace('\r', "\n");
    let blocks: Vec<&str> = content.split("\n\n").collect();

    let mut line_offset = 0;

    for block in blocks {
        let block = block.trim();
        if block.is_empty() {
            line_offset += 2;
            continue;
        }

        let lines: Vec<&str> = block.lines().collect();
        if lines.len() < 2 {
            line_offset += lines.len() + 1;
            continue;
        }

        // Find the timing line (may or may not have index before it)
        let (timing_line_idx, timing_line) = find_timing_line(&lines);

        if timing_line.is_none() {
            line_offset += lines.len() + 1;
            continue;
        }

        let timing_line = timing_line.unwrap();
        let timing_line_num = line_offset + timing_line_idx + 1;

        // Parse timing
        let (start_ms, end_ms) = parse_srt_timing(timing_line)
            .ok_or_else(|| ParseError::invalid_time(timing_line_num, timing_line))?;

        // Text is everything after the timing line
        let text_lines: Vec<&str> = lines[timing_line_idx + 1..].to_vec();
        let text = text_lines.join("\n");

        if !text.is_empty() {
            data.events.push(SubtitleEvent::new(start_ms, end_ms, text));
        }

        line_offset += lines.len() + 1;
    }

    Ok(data)
}

/// Find the timing line in a block of lines.
///
/// Returns (index, Some(line)) if found, or (0, None) if not found.
fn find_timing_line<'a>(lines: &[&'a str]) -> (usize, Option<&'a str>) {
    for (i, line) in lines.iter().enumerate() {
        if line.contains(" --> ") {
            return (i, Some(line));
        }
    }
    (0, None)
}

/// Parse SRT timing line: `HH:MM:SS,mmm --> HH:MM:SS,mmm`
///
/// Returns (start_ms, end_ms) as f64 for precision.
fn parse_srt_timing(line: &str) -> Option<(f64, f64)> {
    let parts: Vec<&str> = line.split(" --> ").collect();
    if parts.len() != 2 {
        return None;
    }

    let start = parse_srt_time(parts[0].trim())?;
    let end = parse_srt_time(parts[1].trim())?;

    Some((start, end))
}

/// Parse SRT timestamp: `HH:MM:SS,mmm` or `HH:MM:SS.mmm`
///
/// Returns time in milliseconds.
pub fn parse_srt_time(s: &str) -> Option<f64> {
    let s = s.trim();

    // Handle both comma and period as decimal separator
    let s = s.replace(',', ".");

    let parts: Vec<&str> = s.split(':').collect();
    if parts.len() != 3 {
        return None;
    }

    let hours: f64 = parts[0].parse().ok()?;
    let minutes: f64 = parts[1].parse().ok()?;

    // Seconds with milliseconds
    let sec_parts: Vec<&str> = parts[2].split('.').collect();
    let seconds: f64 = sec_parts[0].parse().ok()?;

    let milliseconds: f64 = if sec_parts.len() > 1 {
        let ms_str = sec_parts[1];
        let ms_val: f64 = ms_str.parse().ok()?;
        // Normalize based on number of digits
        match ms_str.len() {
            1 => ms_val * 100.0,
            2 => ms_val * 10.0,
            3 => ms_val,
            _ => ms_val / 10f64.powi(ms_str.len() as i32 - 3),
        }
    } else {
        0.0
    };

    Some(hours * 3600000.0 + minutes * 60000.0 + seconds * 1000.0 + milliseconds)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_srt_time() {
        assert!((parse_srt_time("00:00:00,000").unwrap() - 0.0).abs() < 0.001);
        assert!((parse_srt_time("00:00:01,000").unwrap() - 1000.0).abs() < 0.001);
        assert!((parse_srt_time("00:00:01,500").unwrap() - 1500.0).abs() < 0.001);
        assert!((parse_srt_time("00:01:00,000").unwrap() - 60000.0).abs() < 0.001);
        assert!((parse_srt_time("01:00:00,000").unwrap() - 3600000.0).abs() < 0.001);

        // With period instead of comma
        assert!((parse_srt_time("00:00:01.500").unwrap() - 1500.0).abs() < 0.001);
    }

    #[test]
    fn test_parse_srt_timing() {
        let (start, end) = parse_srt_timing("00:00:01,000 --> 00:00:04,500").unwrap();
        assert!((start - 1000.0).abs() < 0.001);
        assert!((end - 4500.0).abs() < 0.001);
    }

    #[test]
    fn test_parse_basic_srt() {
        let content = r#"1
00:00:01,000 --> 00:00:04,000
Hello, world!

2
00:00:05,000 --> 00:00:08,000
This is a test.
With multiple lines.

3
00:00:09,000 --> 00:00:12,000
Final subtitle.
"#;

        let data = parse_srt(content).unwrap();

        assert_eq!(data.format, SubtitleFormat::Srt);
        assert_eq!(data.events.len(), 3);

        // First event
        assert!((data.events[0].start_ms - 1000.0).abs() < 0.001);
        assert!((data.events[0].end_ms - 4000.0).abs() < 0.001);
        assert_eq!(data.events[0].text, "Hello, world!");

        // Second event (multi-line)
        assert!((data.events[1].start_ms - 5000.0).abs() < 0.001);
        assert!((data.events[1].end_ms - 8000.0).abs() < 0.001);
        assert_eq!(data.events[1].text, "This is a test.\nWith multiple lines.");

        // Third event
        assert!((data.events[2].start_ms - 9000.0).abs() < 0.001);
        assert_eq!(data.events[2].text, "Final subtitle.");
    }

    #[test]
    fn test_parse_srt_without_index() {
        // Some SRT files don't have proper indices
        let content = r#"
00:00:01,000 --> 00:00:04,000
Hello, world!

00:00:05,000 --> 00:00:08,000
Another line.
"#;

        let data = parse_srt(content).unwrap();
        assert_eq!(data.events.len(), 2);
    }

    #[test]
    fn test_parse_srt_with_formatting() {
        let content = r#"1
00:00:01,000 --> 00:00:04,000
<i>Italic text</i>

2
00:00:05,000 --> 00:00:08,000
<b>Bold text</b>
"#;

        let data = parse_srt(content).unwrap();
        assert_eq!(data.events.len(), 2);
        assert_eq!(data.events[0].text, "<i>Italic text</i>");
        assert_eq!(data.events[1].text, "<b>Bold text</b>");
    }
}
