//! SRT subtitle writer.
//!
//! Writes SubtitleData to SRT format.
//!
//! # Timing Precision
//!
//! SRT uses millisecond timing (HH:MM:SS,mmm). Internal float milliseconds
//! are rounded according to the configured RoundingMode at write time.

use crate::subtitles::types::{RoundingMode, SubtitleData, SubtitleEvent, WriteOptions};

/// Write SubtitleData to SRT format string.
///
/// # Arguments
/// * `data` - The subtitle data to write.
/// * `options` - Write options (rounding mode, etc.).
///
/// # Returns
/// The SRT file content as a string.
pub fn write_srt(data: &SubtitleData, options: &WriteOptions) -> String {
    let mut output = String::new();

    // Filter to only dialogue events (not comments)
    let dialogue_events: Vec<&SubtitleEvent> =
        data.events.iter().filter(|e| !e.is_comment).collect();

    for (i, event) in dialogue_events.iter().enumerate() {
        if i > 0 {
            output.push('\n');
        }

        // Index (1-based)
        output.push_str(&format!("{}\n", i + 1));

        // Timing line
        let start = format_srt_time(event.start_ms, options.rounding);
        let end = format_srt_time(event.end_ms, options.rounding);
        output.push_str(&format!("{} --> {}\n", start, end));

        // Text (strip ASS formatting tags if present)
        let text = if options.preserve_formatting {
            event.text.clone()
        } else {
            strip_ass_tags(&event.text)
        };
        output.push_str(&text);
        output.push('\n');
    }

    output
}

/// Format milliseconds as SRT timestamp (HH:MM:SS,mmm).
///
/// Applies rounding mode to convert float ms to integer milliseconds.
pub fn format_srt_time(ms: f64, rounding: RoundingMode) -> String {
    // Apply rounding
    let ms = rounding.apply_srt(ms);
    let ms = ms.max(0.0) as u64;

    let millis = ms % 1000;
    let total_secs = ms / 1000;
    let secs = total_secs % 60;
    let total_mins = total_secs / 60;
    let mins = total_mins % 60;
    let hours = total_mins / 60;

    format!("{:02}:{:02}:{:02},{:03}", hours, mins, secs, millis)
}

/// Strip ASS formatting tags from text.
///
/// Converts ASS-style tags like `{\i1}text{\i0}` to plain text.
fn strip_ass_tags(text: &str) -> String {
    let mut result = String::new();
    let mut in_tag = false;

    let mut chars = text.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '{' && chars.peek() == Some(&'\\') {
            in_tag = true;
            continue;
        }

        if c == '}' && in_tag {
            in_tag = false;
            continue;
        }

        if !in_tag {
            result.push(c);
        }
    }

    // Convert ASS line breaks to actual line breaks
    result = result.replace("\\N", "\n");
    result = result.replace("\\n", "\n");

    result
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_srt_time() {
        assert_eq!(format_srt_time(0.0, RoundingMode::Round), "00:00:00,000");
        assert_eq!(format_srt_time(1000.0, RoundingMode::Round), "00:00:01,000");
        assert_eq!(format_srt_time(1500.0, RoundingMode::Round), "00:00:01,500");
        assert_eq!(format_srt_time(60000.0, RoundingMode::Round), "00:01:00,000");
        assert_eq!(
            format_srt_time(3600000.0, RoundingMode::Round),
            "01:00:00,000"
        );

        // Test rounding modes
        assert_eq!(
            format_srt_time(1234.5, RoundingMode::Floor),
            "00:00:01,234"
        );
        assert_eq!(
            format_srt_time(1234.5, RoundingMode::Round),
            "00:00:01,235"
        );
        assert_eq!(format_srt_time(1234.5, RoundingMode::Ceil), "00:00:01,235");
    }

    #[test]
    fn test_strip_ass_tags() {
        assert_eq!(strip_ass_tags(r"{\i1}italic{\i0}"), "italic");
        assert_eq!(strip_ass_tags(r"{\b1}bold{\b0}"), "bold");
        assert_eq!(
            strip_ass_tags(r"{\pos(100,200)}positioned"),
            "positioned"
        );
        assert_eq!(strip_ass_tags(r"Line 1\NLine 2"), "Line 1\nLine 2");
        assert_eq!(strip_ass_tags("No tags"), "No tags");
    }

    #[test]
    fn test_write_basic_srt() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 4000.0, "Hello, world!"));
        data.events
            .push(SubtitleEvent::new(5000.0, 8000.0, "Test subtitle."));

        let options = WriteOptions::default();
        let output = write_srt(&data, &options);

        let expected = "1\n00:00:01,000 --> 00:00:04,000\nHello, world!\n\n2\n00:00:05,000 --> 00:00:08,000\nTest subtitle.\n";

        assert_eq!(output, expected);
    }

    #[test]
    fn test_skip_comments() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 4000.0, "Dialogue"));

        let mut comment = SubtitleEvent::new(2000.0, 3000.0, "Comment");
        comment.is_comment = true;
        data.events.push(comment);

        data.events
            .push(SubtitleEvent::new(5000.0, 8000.0, "More dialogue"));

        let output = write_srt(&data, &WriteOptions::default());

        // Should have indices 1 and 2, skipping the comment
        assert!(output.contains("1\n00:00:01,000"));
        assert!(output.contains("2\n00:00:05,000"));
        assert!(!output.contains("Comment"));
    }
}
