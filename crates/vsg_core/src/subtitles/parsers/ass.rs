//! ASS/SSA subtitle parser.
//!
//! Parses Advanced SubStation Alpha (.ass) and SubStation Alpha (.ssa) files.
//!
//! # Format Overview
//!
//! ASS files have three main sections:
//! - `[Script Info]`: Metadata (title, resolution, etc.)
//! - `[V4+ Styles]` or `[V4 Styles]`: Style definitions
//! - `[Events]`: Dialogue and comment lines
//!
//! All timing is in the format `H:MM:SS.cc` (centiseconds).

use crate::subtitles::error::ParseError;
use crate::subtitles::types::{
    AssColor, SubtitleData, SubtitleEvent, SubtitleFormat, SubtitleMetadata, SubtitleStyle,
};

/// Parse ASS/SSA content into SubtitleData.
///
/// # Arguments
/// * `content` - The raw ASS file content as a string.
///
/// # Returns
/// * `Ok(SubtitleData)` - Parsed subtitle data.
/// * `Err(ParseError)` - If parsing fails.
pub fn parse_ass(content: &str) -> Result<SubtitleData, ParseError> {
    let mut data = SubtitleData::with_format(SubtitleFormat::Ass);
    let mut current_section = String::new();
    let mut style_format: Vec<String> = Vec::new();
    let mut event_format: Vec<String> = Vec::new();

    for (line_num, line) in content.lines().enumerate() {
        let line_num = line_num + 1; // 1-indexed for error messages
        let line = line.trim();

        // Skip empty lines and BOM
        if line.is_empty() || line == "\u{feff}" {
            continue;
        }

        // Section header
        if line.starts_with('[') && line.ends_with(']') {
            current_section = line[1..line.len() - 1].to_string();
            continue;
        }

        // Skip comments (lines starting with ; or !)
        if line.starts_with(';') || line.starts_with('!') {
            continue;
        }

        // Parse based on current section
        match current_section.to_lowercase().as_str() {
            "script info" => {
                parse_script_info_line(line, &mut data.metadata);
            }
            "v4+ styles" | "v4 styles" => {
                if line.starts_with("Format:") {
                    style_format = parse_format_line(line);
                } else if line.starts_with("Style:") {
                    if let Some(style) = parse_style_line(line, &style_format, line_num)? {
                        data.styles.push(style);
                    }
                }
            }
            "events" => {
                if line.starts_with("Format:") {
                    event_format = parse_format_line(line);
                } else if line.starts_with("Dialogue:") || line.starts_with("Comment:") {
                    let is_comment = line.starts_with("Comment:");
                    if let Some(event) = parse_event_line(line, &event_format, is_comment, line_num)?
                    {
                        data.events.push(event);
                    }
                }
            }
            _ => {
                // Unknown section - store in custom metadata
                if let Some((key, value)) = line.split_once(':') {
                    data.metadata
                        .custom
                        .insert(key.trim().to_string(), value.trim().to_string());
                }
            }
        }
    }

    // Ensure we have a default style if none defined
    if data.styles.is_empty() {
        data.styles.push(SubtitleStyle::default());
    }

    Ok(data)
}

/// Parse a Format: line to get field names.
fn parse_format_line(line: &str) -> Vec<String> {
    line.trim_start_matches("Format:")
        .split(',')
        .map(|s| s.trim().to_lowercase())
        .collect()
}

/// Parse a Script Info line.
fn parse_script_info_line(line: &str, metadata: &mut SubtitleMetadata) {
    let Some((key, value)) = line.split_once(':') else {
        return;
    };

    let key = key.trim().to_lowercase();
    let value = value.trim();

    match key.as_str() {
        "title" => metadata.title = Some(value.to_string()),
        "original script" => metadata.original_script = Some(value.to_string()),
        "original translation" | "translation" => metadata.translation = Some(value.to_string()),
        "original timing" | "timing" => metadata.timing = Some(value.to_string()),
        "playresx" => metadata.play_res_x = value.parse().ok(),
        "playresy" => metadata.play_res_y = value.parse().ok(),
        "scripttype" => metadata.script_type = Some(value.to_string()),
        "wrapstyle" => metadata.wrap_style = value.parse().ok(),
        "scaledborderandshadow" => {
            metadata.scaled_border_and_shadow = Some(value == "yes" || value == "1")
        }
        "ycbcr matrix" => metadata.ycbcr_matrix = Some(value.to_string()),
        _ => {
            metadata.custom.insert(key, value.to_string());
        }
    }
}

/// Parse a Style: line.
fn parse_style_line(
    line: &str,
    format: &[String],
    line_num: usize,
) -> Result<Option<SubtitleStyle>, ParseError> {
    let content = line.trim_start_matches("Style:").trim();
    let fields: Vec<&str> = content.split(',').collect();

    // Use default format if none specified
    let format = if format.is_empty() {
        default_style_format()
    } else {
        format.to_vec()
    };

    if fields.len() < format.len() {
        return Err(ParseError::invalid_style(
            line_num,
            format!("Expected {} fields, got {}", format.len(), fields.len()),
        ));
    }

    let mut style = SubtitleStyle::default();

    for (i, field_name) in format.iter().enumerate() {
        let value = fields.get(i).map(|s| s.trim()).unwrap_or("");

        match field_name.as_str() {
            "name" => style.name = value.to_string(),
            "fontname" => style.fontname = value.to_string(),
            "fontsize" => style.fontsize = value.parse().unwrap_or(20.0),
            "primarycolour" => {
                style.primary_color = AssColor::from_ass_string(value).unwrap_or_default()
            }
            "secondarycolour" => {
                style.secondary_color = AssColor::from_ass_string(value).unwrap_or_default()
            }
            "outlinecolour" | "tertiarycolour" => {
                style.outline_color = AssColor::from_ass_string(value).unwrap_or_default()
            }
            "backcolour" => {
                style.back_color = AssColor::from_ass_string(value).unwrap_or_default()
            }
            "bold" => style.bold = value == "-1" || value == "1",
            "italic" => style.italic = value == "-1" || value == "1",
            "underline" => style.underline = value == "-1" || value == "1",
            "strikeout" => style.strikeout = value == "-1" || value == "1",
            "scalex" => style.scale_x = value.parse().unwrap_or(100.0),
            "scaley" => style.scale_y = value.parse().unwrap_or(100.0),
            "spacing" => style.spacing = value.parse().unwrap_or(0.0),
            "angle" => style.angle = value.parse().unwrap_or(0.0),
            "borderstyle" => style.border_style = value.parse().unwrap_or(1),
            "outline" => style.outline = value.parse().unwrap_or(2.0),
            "shadow" => style.shadow = value.parse().unwrap_or(2.0),
            "alignment" => style.alignment = value.parse().unwrap_or(2),
            "marginl" => style.margin_l = value.parse().unwrap_or(10),
            "marginr" => style.margin_r = value.parse().unwrap_or(10),
            "marginv" => style.margin_v = value.parse().unwrap_or(10),
            "encoding" => style.encoding = value.parse().unwrap_or(1),
            _ => {}
        }
    }

    Ok(Some(style))
}

/// Parse a Dialogue: or Comment: line.
fn parse_event_line(
    line: &str,
    format: &[String],
    is_comment: bool,
    line_num: usize,
) -> Result<Option<SubtitleEvent>, ParseError> {
    let prefix = if is_comment { "Comment:" } else { "Dialogue:" };
    let content = line.trim_start_matches(prefix).trim();

    // Use default format if none specified
    let format = if format.is_empty() {
        default_event_format()
    } else {
        format.to_vec()
    };

    // Find the text field index (last field, may contain commas)
    let text_index = format.iter().position(|f| f == "text").unwrap_or(9);

    // Split only up to the text field
    let parts: Vec<&str> = content.splitn(text_index + 1, ',').collect();

    if parts.len() < text_index {
        return Err(ParseError::invalid_event(
            line_num,
            format!("Expected at least {} fields", text_index),
        ));
    }

    let mut event = SubtitleEvent {
        is_comment,
        ..Default::default()
    };

    for (i, field_name) in format.iter().enumerate() {
        let value = parts.get(i).map(|s| s.trim()).unwrap_or("");

        match field_name.as_str() {
            "layer" | "marked" => event.layer = value.parse().unwrap_or(0),
            "start" => {
                event.start_ms = parse_ass_time(value)
                    .ok_or_else(|| ParseError::invalid_time(line_num, value))?;
            }
            "end" => {
                event.end_ms = parse_ass_time(value)
                    .ok_or_else(|| ParseError::invalid_time(line_num, value))?;
            }
            "style" => event.style = Some(value.to_string()),
            "name" | "actor" => {
                if !value.is_empty() {
                    event.actor = Some(value.to_string());
                }
            }
            "marginl" => event.margin_l = value.parse().ok(),
            "marginr" => event.margin_r = value.parse().ok(),
            "marginv" => event.margin_v = value.parse().ok(),
            "effect" => {
                if !value.is_empty() {
                    event.effect = Some(value.to_string());
                }
            }
            "text" => event.text = value.to_string(),
            _ => {}
        }
    }

    Ok(Some(event))
}

/// Parse ASS timestamp format: H:MM:SS.cc
///
/// Returns time in milliseconds (f64 for precision).
pub fn parse_ass_time(s: &str) -> Option<f64> {
    let s = s.trim();

    // Format: H:MM:SS.cc or H:MM:SS.ccc
    let parts: Vec<&str> = s.split(':').collect();
    if parts.len() != 3 {
        return None;
    }

    let hours: f64 = parts[0].parse().ok()?;
    let minutes: f64 = parts[1].parse().ok()?;

    // Seconds may have centiseconds or milliseconds after decimal
    let sec_parts: Vec<&str> = parts[2].split('.').collect();
    let seconds: f64 = sec_parts[0].parse().ok()?;

    let fractional = if sec_parts.len() > 1 {
        let frac_str = sec_parts[1];
        let frac_val: f64 = frac_str.parse().ok()?;
        // Normalize based on number of digits
        match frac_str.len() {
            1 => frac_val * 100.0,  // Tenths to ms
            2 => frac_val * 10.0,   // Centiseconds to ms
            3 => frac_val,          // Milliseconds
            _ => frac_val / 10f64.powi(frac_str.len() as i32 - 3),
        }
    } else {
        0.0
    };

    Some(hours * 3600000.0 + minutes * 60000.0 + seconds * 1000.0 + fractional)
}

/// Default style format for V4+ Styles.
fn default_style_format() -> Vec<String> {
    vec![
        "name",
        "fontname",
        "fontsize",
        "primarycolour",
        "secondarycolour",
        "outlinecolour",
        "backcolour",
        "bold",
        "italic",
        "underline",
        "strikeout",
        "scalex",
        "scaley",
        "spacing",
        "angle",
        "borderstyle",
        "outline",
        "shadow",
        "alignment",
        "marginl",
        "marginr",
        "marginv",
        "encoding",
    ]
    .into_iter()
    .map(String::from)
    .collect()
}

/// Default event format for Events section.
fn default_event_format() -> Vec<String> {
    vec![
        "layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text",
    ]
    .into_iter()
    .map(String::from)
    .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_ass_time() {
        // Standard format
        assert!((parse_ass_time("0:00:00.00").unwrap() - 0.0).abs() < 0.001);
        assert!((parse_ass_time("0:00:01.00").unwrap() - 1000.0).abs() < 0.001);
        assert!((parse_ass_time("0:00:01.50").unwrap() - 1500.0).abs() < 0.001);
        assert!((parse_ass_time("0:01:00.00").unwrap() - 60000.0).abs() < 0.001);
        assert!((parse_ass_time("1:00:00.00").unwrap() - 3600000.0).abs() < 0.001);

        // With centiseconds
        assert!((parse_ass_time("0:00:00.01").unwrap() - 10.0).abs() < 0.001);
        assert!((parse_ass_time("0:00:00.99").unwrap() - 990.0).abs() < 0.001);
    }

    #[test]
    fn test_parse_basic_ass() {
        let content = r#"[Script Info]
Title: Test Subtitle
PlayResX: 1920
PlayResY: 1080

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,Hello, world!
Dialogue: 0,0:00:05.00,0:00:08.00,Default,,0,0,0,,This is a test.
Comment: 0,0:00:09.00,0:00:10.00,Default,,0,0,0,,This is a comment
"#;

        let data = parse_ass(content).unwrap();

        // Check metadata
        assert_eq!(data.metadata.title, Some("Test Subtitle".to_string()));
        assert_eq!(data.metadata.play_res_x, Some(1920));
        assert_eq!(data.metadata.play_res_y, Some(1080));

        // Check styles
        assert_eq!(data.styles.len(), 1);
        assert_eq!(data.styles[0].name, "Default");
        assert_eq!(data.styles[0].fontname, "Arial");
        assert_eq!(data.styles[0].fontsize, 20.0);

        // Check events
        assert_eq!(data.events.len(), 3);

        // First dialogue
        assert!(!data.events[0].is_comment);
        assert!((data.events[0].start_ms - 1000.0).abs() < 0.001);
        assert!((data.events[0].end_ms - 4000.0).abs() < 0.001);
        assert_eq!(data.events[0].text, "Hello, world!");

        // Second dialogue
        assert!(!data.events[1].is_comment);
        assert!((data.events[1].start_ms - 5000.0).abs() < 0.001);
        assert_eq!(data.events[1].text, "This is a test.");

        // Comment
        assert!(data.events[2].is_comment);
        assert_eq!(data.events[2].text, "This is a comment");

        // Dialogue count (excludes comments)
        assert_eq!(data.dialogue_count(), 2);
    }

    #[test]
    fn test_parse_format_line() {
        let format = parse_format_line("Format: Name, Fontname, Fontsize, PrimaryColour");
        assert_eq!(
            format,
            vec!["name", "fontname", "fontsize", "primarycolour"]
        );
    }
}
