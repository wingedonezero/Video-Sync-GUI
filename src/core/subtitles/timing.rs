//! Subtitle timing fixes
//!
//! Implements three-phase timing correction for ASS/SSA subtitles:
//! 1. Fix long durations (trim excessive display time)
//! 2. Fix overlaps (prevent subtitle collisions)
//! 3. Fix short durations (extend minimum reading time)

use crate::core::models::results::CoreResult;
use std::path::Path;

/// Subtitle event (simplified representation)
#[derive(Debug, Clone)]
struct SubtitleEvent {
    start_ms: i64,
    end_ms: i64,
    text: String,
    raw_line: String,
    line_index: usize,
}

/// Parse subtitle events from ASS/SSA file
fn parse_events(content: &str) -> Vec<SubtitleEvent> {
    let mut events = Vec::new();
    let mut in_events = false;
    let mut format_indices: Option<(usize, usize, usize)> = None; // (start, end, text)

    for (idx, line) in content.lines().enumerate() {
        let trimmed = line.trim();

        // Track section
        if trimmed.starts_with('[') && trimmed.ends_with(']') {
            in_events = trimmed.to_lowercase().contains("events");
            continue;
        }

        if !in_events {
            continue;
        }

        // Parse format line to get field indices
        if trimmed.to_lowercase().starts_with("format:") {
            let fields: Vec<String> = trimmed["format:".len()..]
                .split(',')
                .map(|s| s.trim().to_lowercase())
                .collect();

            let start_idx = fields.iter().position(|f| f.as_str() == "start");
            let end_idx = fields.iter().position(|f| f.as_str() == "end");
            let text_idx = fields.iter().position(|f| f.as_str() == "text");

            if let (Some(s), Some(e), Some(t)) = (start_idx, end_idx, text_idx) {
                format_indices = Some((s, e, t));
            }
            continue;
        }

        // Parse dialogue/comment lines
        if trimmed.to_lowercase().starts_with("dialogue:")
            || trimmed.to_lowercase().starts_with("comment:")
        {
            if let Some((start_idx, end_idx, text_idx)) = format_indices {
                let prefix_end = trimmed.find(':').unwrap() + 1;
                let fields: Vec<&str> = trimmed[prefix_end..].splitn(text_idx + 1, ',').collect();

                if fields.len() > text_idx {
                    if let (Ok(start_ms), Ok(end_ms)) = (
                        parse_timestamp(fields[start_idx].trim()),
                        parse_timestamp(fields[end_idx].trim()),
                    ) {
                        let text = fields[text_idx].to_string();
                        events.push(SubtitleEvent {
                            start_ms,
                            end_ms,
                            text: strip_ass_tags(&text),
                            raw_line: line.to_string(),
                            line_index: idx,
                        });
                    }
                }
            }
        }
    }

    events
}

/// Parse ASS timestamp (H:MM:SS.CS) to milliseconds
fn parse_timestamp(s: &str) -> Result<i64, ()> {
    let parts: Vec<&str> = s.split(&[':', '.']).collect();
    if parts.len() != 4 {
        return Err(());
    }

    let hours: i64 = parts[0].parse().map_err(|_| ())?;
    let minutes: i64 = parts[1].parse().map_err(|_| ())?;
    let seconds: i64 = parts[2].parse().map_err(|_| ())?;
    let centiseconds: i64 = parts[3].parse().map_err(|_| ())?;

    Ok((hours * 3600 + minutes * 60 + seconds) * 1000 + centiseconds * 10)
}

/// Format milliseconds to ASS timestamp (H:MM:SS.CS)
fn format_timestamp(ms: i64) -> String {
    let total_seconds = ms / 1000;
    let centiseconds = (ms % 1000) / 10;

    let hours = total_seconds / 3600;
    let minutes = (total_seconds % 3600) / 60;
    let seconds = total_seconds % 60;

    format!("{}:{:02}:{:02}.{:02}", hours, minutes, seconds, centiseconds)
}

/// Strip ASS formatting tags from text
fn strip_ass_tags(text: &str) -> String {
    let mut result = String::new();
    let mut in_tag = false;

    for ch in text.chars() {
        if ch == '{' {
            in_tag = true;
        } else if ch == '}' {
            in_tag = false;
        } else if !in_tag {
            result.push(ch);
        }
    }

    result
}

/// Update event timestamps in the original content
fn update_event_timestamps(
    content: &str,
    events: &[SubtitleEvent],
    new_times: &[(i64, i64)],
) -> String {
    let lines: Vec<&str> = content.lines().collect();
    let mut new_lines = Vec::new();

    for (idx, line) in lines.iter().enumerate() {
        // Find if this line is an event we modified
        if let Some(event_idx) = events.iter().position(|e| e.line_index == idx) {
            let (new_start, new_end) = new_times[event_idx];

            // Replace timestamps in the line
            let mut new_line = line.to_string();

            // Find and replace start and end timestamps
            // This is a simplified approach - in production you'd parse properly
            if let (Ok(old_start), Ok(old_end)) = (
                parse_timestamp(
                    &line.split(',')
                        .nth(1)
                        .unwrap_or("")
                        .trim(),
                ),
                parse_timestamp(
                    &line.split(',')
                        .nth(2)
                        .unwrap_or("")
                        .trim(),
                ),
            ) {
                let old_start_str = format_timestamp(old_start);
                let old_end_str = format_timestamp(old_end);
                let new_start_str = format_timestamp(new_start);
                let new_end_str = format_timestamp(new_end);

                // Replace first occurrence (start time) then second (end time)
                new_line = new_line.replacen(&old_start_str, &new_start_str, 1);
                new_line = new_line.replacen(&old_end_str, &new_end_str, 1);
            }

            new_lines.push(new_line);
        } else {
            new_lines.push(line.to_string());
        }
    }

    new_lines.join("\n")
}

/// Fix subtitle timing issues (three-phase algorithm)
///
/// Phase 1: Fix long durations (trim excessive display time)
/// Phase 2: Fix overlaps (prevent subtitle collisions)
/// Phase 3: Fix short durations (extend minimum reading time)
///
/// # Arguments
/// * `subtitle_path` - Path to the ASS/SSA file
/// * `max_cps` - Maximum characters per second for reading (default: 20.0)
/// * `min_duration_ms` - Minimum subtitle duration (default: 500ms)
/// * `min_gap_ms` - Minimum gap between subtitles (default: 1ms)
///
/// # Returns
/// Number of events fixed
pub fn fix_timing(
    subtitle_path: &Path,
    max_cps: f64,
    min_duration_ms: i64,
    min_gap_ms: i64,
) -> CoreResult<usize> {
    let content = std::fs::read_to_string(subtitle_path)?;
    let mut events = parse_events(&content);

    if events.is_empty() {
        return Ok(0);
    }

    // Sort by start time
    events.sort_by_key(|e| e.start_ms);

    let mut fixed_count = 0;
    let mut new_times: Vec<(i64, i64)> = events.iter().map(|e| (e.start_ms, e.end_ms)).collect();

    // Phase 1: Fix long durations
    for i in 0..events.len() {
        let text_len = events[i].text.replace(' ', "").len();
        if text_len == 0 {
            continue;
        }

        // Calculate ideal reading time
        let ideal_duration_ms = ((text_len as f64 / max_cps) * 1000.0 * 1.1) as i64; // +10% buffer
        let ideal_duration_ms = ideal_duration_ms.max(min_duration_ms);

        let current_duration = new_times[i].1 - new_times[i].0;

        // Only trim if significantly longer (+100ms tolerance)
        if current_duration > ideal_duration_ms + 100 {
            new_times[i].1 = new_times[i].0 + ideal_duration_ms;
            fixed_count += 1;
        }
    }

    // Phase 2: Fix overlaps
    for i in 0..events.len().saturating_sub(1) {
        let next_start = new_times[i + 1].0;

        if new_times[i].1 > next_start {
            // Overlap detected
            let new_end = next_start - min_gap_ms;

            // Only trim if duration remains ≥100ms (emergency minimum)
            if new_end > new_times[i].0 + 100 {
                new_times[i].1 = new_end;
                fixed_count += 1;
            }
        }
    }

    // Phase 3: Fix short durations
    for i in 0..events.len() {
        let duration = new_times[i].1 - new_times[i].0;

        if duration > 0 && duration < min_duration_ms {
            let mut new_end = new_times[i].0 + min_duration_ms;

            // Don't extend into next subtitle (leave gap)
            if i + 1 < events.len() {
                let next_start = new_times[i + 1].0;
                new_end = new_end.min(next_start - min_gap_ms);
            }

            if new_end > new_times[i].1 {
                new_times[i].1 = new_end;
                fixed_count += 1;
            }
        }
    }

    // Write back modified content
    let new_content = update_event_timestamps(&content, &events, &new_times);
    std::fs::write(subtitle_path, new_content)?;

    Ok(fixed_count)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_timestamp() {
        assert_eq!(parse_timestamp("0:00:05.00"), Ok(5000));
        assert_eq!(parse_timestamp("0:01:30.50"), Ok(90500));
        assert_eq!(parse_timestamp("1:00:00.00"), Ok(3600000));
    }

    #[test]
    fn test_format_timestamp() {
        assert_eq!(format_timestamp(5000), "0:00:05.00");
        assert_eq!(format_timestamp(90500), "0:01:30.50");
        assert_eq!(format_timestamp(3600000), "1:00:00.00");
    }

    #[test]
    fn test_strip_ass_tags() {
        assert_eq!(strip_ass_tags("Hello {\\b1}World{\\b0}"), "Hello World");
        assert_eq!(strip_ass_tags("{\\i1}Italic{\\i0} text"), "Italic text");
        assert_eq!(strip_ass_tags("No tags"), "No tags");
    }
}
