//! Chapter XML processing
//!
//! Handles extraction, modification, and repackaging of MKV chapter metadata:
//! - Extract chapters from MKV using mkvextract
//! - Parse XML with namespace awareness
//! - Shift timestamps by global delay
//! - Snap chapter times to video keyframes
//! - Rename chapters to "Chapter NN"
//! - Normalize/deduplicate chapter entries
//! - Write modified XML for mkvmerge

use crate::core::chapters::keyframes::probe_keyframes_ns;
use crate::core::io::runner::CommandRunner;
use crate::core::models::results::CoreResult;
use quick_xml::events::{BytesEnd, BytesStart, BytesText, Event};
use quick_xml::{Reader, Writer};
use std::collections::HashMap;
use std::io::Cursor;
use std::path::{Path, PathBuf};

/// Snap mode for keyframe snapping
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SnapMode {
    Previous, // Snap to previous keyframe
    Nearest,  // Snap to nearest keyframe
}

/// Statistics from chapter processing
#[derive(Debug, Default)]
pub struct ChapterStats {
    pub moved: usize,
    pub on_kf: usize,
    pub too_far: usize,
}

/// Process chapters from an MKV file
///
/// # Arguments
/// * `mkv_path` - Path to the MKV file
/// * `temp_dir` - Temporary directory for output
/// * `shift_ms` - Global shift in milliseconds
/// * `config` - Configuration map (snap_chapters, rename_chapters, etc.)
/// * `runner` - Command runner
/// * `video_path` - Optional path to video for keyframe snapping
///
/// # Returns
/// Path to the modified chapters XML file, or None if no chapters found
pub fn process_chapters(
    mkv_path: &Path,
    temp_dir: &Path,
    shift_ms: i64,
    config: &HashMap<String, serde_json::Value>,
    runner: &CommandRunner,
    video_path: Option<&Path>,
) -> CoreResult<Option<PathBuf>> {
    // Extract chapters XML from MKV
    let xml_content = extract_chapters_xml(mkv_path, runner)?;

    if xml_content.is_empty() {
        runner.log("[Chapters] No chapters found in source file.");
        return Ok(None);
    }

    // Parse XML
    let mut doc = parse_chapters_xml(&xml_content)?;

    // Shift timestamps
    let shift_ns = shift_ms * 1_000_000;
    if shift_ns != 0 {
        shift_chapter_times(&mut doc, shift_ns);
        runner.log(&format!("[Chapters] Shifted all timestamps by {} ms.", shift_ms));
    }

    // Rename chapters if requested
    if config.get("rename_chapters").and_then(|v| v.as_bool()).unwrap_or(false) {
        rename_chapters(&mut doc);
        runner.log("[Chapters] Renamed chapters to \"Chapter NN\".");
    }

    // Keyframe snapping if requested
    if config.get("snap_chapters").and_then(|v| v.as_bool()).unwrap_or(false) {
        if let Some(vid_path) = video_path {
            let keyframes = probe_keyframes_ns(vid_path, runner)?;
            let threshold_ms = config
                .get("snap_threshold_ms")
                .and_then(|v| v.as_i64())
                .unwrap_or(250);
            let starts_only = config
                .get("snap_starts_only")
                .and_then(|v| v.as_bool())
                .unwrap_or(true);
            let snap_mode = match config
                .get("snap_mode")
                .and_then(|v| v.as_str())
                .unwrap_or("previous")
            {
                "nearest" => SnapMode::Nearest,
                _ => SnapMode::Previous,
            };

            let stats = snap_chapter_times(&mut doc, &keyframes, threshold_ms, starts_only, snap_mode);
            runner.log(&format!(
                "[Chapters] Snap result: moved={}, on_kf={}, too_far={} (kfs={}, mode={:?}, thr={}ms, starts_only={})",
                stats.moved, stats.on_kf, stats.too_far, keyframes.len(), snap_mode, threshold_ms, starts_only
            ));
        }
    }

    // Normalize chapter end times
    normalize_chapters(&mut doc);

    // Write modified XML
    let output_path = temp_dir.join(format!(
        "{}_chapters_modified.xml",
        mkv_path.file_stem().unwrap().to_str().unwrap()
    ));

    let xml_output = write_chapters_xml(&doc)?;
    std::fs::write(&output_path, xml_output)?;

    Ok(Some(output_path))
}

/// Extract chapters XML from MKV file using mkvextract
fn extract_chapters_xml(
    mkv_path: &Path,
    runner: &CommandRunner,
) -> CoreResult<String> {
    let cmd = vec![
        "mkvextract",
        mkv_path.to_str().unwrap(),
        "chapters",
        "-",
    ];

    Ok(runner.run(&cmd)?.stdout)
}

/// Chapter document structure (simplified DOM)
#[derive(Debug)]
pub struct ChapterDoc {
    pub atoms: Vec<ChapterAtom>,
}

#[derive(Debug)]
pub struct ChapterAtom {
    pub start_ns: i64,
    pub end_ns: i64,
    pub display: ChapterDisplay,
}

#[derive(Debug)]
pub struct ChapterDisplay {
    pub string: String,
    pub language: String,
    pub language_ietf: String,
}

/// Parse chapters XML into simplified structure
fn parse_chapters_xml(xml: &str) -> CoreResult<ChapterDoc> {
    let mut reader = Reader::from_str(xml);
    reader.trim_text(true);

    let mut atoms = Vec::new();
    let mut current_atom: Option<ChapterAtom> = None;
    let mut in_atom = false;
    let mut in_display = false;
    let mut current_tag = String::new();

    loop {
        match reader.read_event() {
            Ok(Event::Start(e)) => {
                let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                current_tag = name.clone();

                if name.contains("ChapterAtom") {
                    in_atom = true;
                    current_atom = Some(ChapterAtom {
                        start_ns: 0,
                        end_ns: 0,
                        display: ChapterDisplay {
                            string: String::new(),
                            language: "und".to_string(),
                            language_ietf: "und".to_string(),
                        },
                    });
                } else if name.contains("ChapterDisplay") {
                    in_display = true;
                }
            }
            Ok(Event::Text(e)) => {
                if !in_atom {
                    continue;
                }

                let text = e.unescape().unwrap_or_default().to_string();

                if let Some(atom) = current_atom.as_mut() {
                    if current_tag.contains("ChapterTimeStart") {
                        atom.start_ns = parse_timestamp_ns(&text);
                    } else if current_tag.contains("ChapterTimeEnd") {
                        atom.end_ns = parse_timestamp_ns(&text);
                    } else if in_display {
                        if current_tag.contains("ChapterString") {
                            atom.display.string = text;
                        } else if current_tag.contains("ChapLanguageIETF") {
                            atom.display.language_ietf = text;
                        } else if current_tag.contains("ChapterLanguage") {
                            atom.display.language = text;
                        }
                    }
                }
            }
            Ok(Event::End(e)) => {
                let name = String::from_utf8_lossy(e.name().as_ref()).to_string();

                if name.contains("ChapterAtom") {
                    if let Some(atom) = current_atom.take() {
                        atoms.push(atom);
                    }
                    in_atom = false;
                } else if name.contains("ChapterDisplay") {
                    in_display = false;
                }
            }
            Ok(Event::Eof) => break,
            Err(e) => {
                return Err(format!("XML parse error at position {}: {:?}", reader.buffer_position(), e).into())
            }
            _ => {}
        }
    }

    Ok(ChapterDoc { atoms })
}

/// Parse timestamp from XML format (HH:MM:SS.nnnnnnnnn) to nanoseconds
fn parse_timestamp_ns(s: &str) -> i64 {
    let parts: Vec<&str> = s.split(&[':',  '.']).collect();
    if parts.len() < 3 {
        return 0;
    }

    let hours: i64 = parts[0].parse().unwrap_or(0);
    let minutes: i64 = parts[1].parse().unwrap_or(0);
    let seconds: i64 = parts[2].parse().unwrap_or(0);

    let mut ns = (hours * 3600 + minutes * 60 + seconds) * 1_000_000_000;

    // Add fractional nanoseconds if present
    if parts.len() > 3 {
        // Pad to 9 digits
        let frac = format!("{:0<9}", parts[3]);
        ns += frac.parse::<i64>().unwrap_or(0);
    }

    ns
}

/// Format nanoseconds to XML timestamp format (HH:MM:SS.nnnnnnnnn)
fn format_timestamp_ns(ns: i64) -> String {
    let total_seconds = ns / 1_000_000_000;
    let nanos = ns % 1_000_000_000;

    let hours = total_seconds / 3600;
    let minutes = (total_seconds % 3600) / 60;
    let seconds = total_seconds % 60;

    format!("{:02}:{:02}:{:02}.{:09}", hours, minutes, seconds, nanos)
}

/// Shift all chapter timestamps by a given amount (nanoseconds)
fn shift_chapter_times(doc: &mut ChapterDoc, shift_ns: i64) {
    for atom in &mut doc.atoms {
        atom.start_ns += shift_ns;
        atom.end_ns += shift_ns;
    }
}

/// Rename chapters to "Chapter NN" format
fn rename_chapters(doc: &mut ChapterDoc) {
    for (i, atom) in doc.atoms.iter_mut().enumerate() {
        atom.display.string = format!("Chapter {:02}", i + 1);
    }
}

/// Snap chapter times to keyframes
fn snap_chapter_times(
    doc: &mut ChapterDoc,
    keyframes: &[i64],
    threshold_ms: i64,
    starts_only: bool,
    mode: SnapMode,
) -> ChapterStats {
    let mut stats = ChapterStats::default();
    let threshold_ns = threshold_ms * 1_000_000;

    for atom in &mut doc.atoms {
        // Snap start time
        if let Some(snapped) = find_snap_target(atom.start_ns, keyframes, threshold_ns, mode) {
            if snapped == atom.start_ns {
                stats.on_kf += 1;
            } else {
                atom.start_ns = snapped;
                stats.moved += 1;
            }
        } else {
            stats.too_far += 1;
        }

        // Snap end time if requested
        if !starts_only {
            if let Some(snapped) = find_snap_target(atom.end_ns, keyframes, threshold_ns, mode) {
                atom.end_ns = snapped;
            }
        }
    }

    stats
}

/// Find snap target for a timestamp
fn find_snap_target(ts_ns: i64, keyframes: &[i64], threshold_ns: i64, mode: SnapMode) -> Option<i64> {
    if keyframes.is_empty() {
        return None;
    }

    // Binary search for previous keyframe
    let idx = match keyframes.binary_search(&ts_ns) {
        Ok(i) => return Some(keyframes[i]), // Exact match
        Err(i) => i,
    };

    match mode {
        SnapMode::Previous => {
            if idx == 0 {
                return None; // No previous keyframe
            }
            let prev = keyframes[idx - 1];
            if (ts_ns - prev).abs() <= threshold_ns {
                Some(prev)
            } else {
                None
            }
        }
        SnapMode::Nearest => {
            let prev = if idx > 0 { Some(keyframes[idx - 1]) } else { None };
            let next = if idx < keyframes.len() { Some(keyframes[idx]) } else { None };

            match (prev, next) {
                (Some(p), Some(n)) => {
                    let dist_prev = (ts_ns - p).abs();
                    let dist_next = (n - ts_ns).abs();
                    let closest = if dist_prev <= dist_next { p } else { n };
                    if (ts_ns - closest).abs() <= threshold_ns {
                        Some(closest)
                    } else {
                        None
                    }
                }
                (Some(p), None) => {
                    if (ts_ns - p).abs() <= threshold_ns {
                        Some(p)
                    } else {
                        None
                    }
                }
                (None, Some(n)) => {
                    if (n - ts_ns).abs() <= threshold_ns {
                        Some(n)
                    } else {
                        None
                    }
                }
                (None, None) => None,
            }
        }
    }
}

/// Normalize chapter end times (dedupe and fix overlaps)
fn normalize_chapters(doc: &mut ChapterDoc) {
    // Sort by start time
    doc.atoms.sort_by_key(|a| a.start_ns);

    // Remove duplicates (same start time)
    doc.atoms.dedup_by_key(|a| a.start_ns);

    // Fix end times to match next chapter's start
    for i in 0..doc.atoms.len() {
        if i + 1 < doc.atoms.len() {
            let next_start = doc.atoms[i + 1].start_ns;
            doc.atoms[i].end_ns = next_start;
        } else {
            // Last chapter: ensure end > start
            if doc.atoms[i].end_ns <= doc.atoms[i].start_ns {
                doc.atoms[i].end_ns = doc.atoms[i].start_ns + 1_000_000_000; // +1 second
            }
        }
    }
}

/// Write chapters XML from document structure
fn write_chapters_xml(doc: &ChapterDoc) -> CoreResult<Vec<u8>> {
    let mut writer = Writer::new(Cursor::new(Vec::new()));

    // XML declaration
    writer.write_event(Event::Decl(quick_xml::events::BytesDecl::new("1.0", Some("UTF-8"), None)))?;

    // Root element
    writer.write_event(Event::Start(BytesStart::new("Chapters")))?;

    // EditionEntry
    writer.write_event(Event::Start(BytesStart::new("EditionEntry")))?;

    // Write each chapter atom
    for atom in &doc.atoms {
        writer.write_event(Event::Start(BytesStart::new("ChapterAtom")))?;

        // ChapterTimeStart
        writer.write_event(Event::Start(BytesStart::new("ChapterTimeStart")))?;
        writer.write_event(Event::Text(BytesText::new(&format_timestamp_ns(atom.start_ns))))?;
        writer.write_event(Event::End(BytesEnd::new("ChapterTimeStart")))?;

        // ChapterTimeEnd
        writer.write_event(Event::Start(BytesStart::new("ChapterTimeEnd")))?;
        writer.write_event(Event::Text(BytesText::new(&format_timestamp_ns(atom.end_ns))))?;
        writer.write_event(Event::End(BytesEnd::new("ChapterTimeEnd")))?;

        // ChapterDisplay
        writer.write_event(Event::Start(BytesStart::new("ChapterDisplay")))?;

        writer.write_event(Event::Start(BytesStart::new("ChapterString")))?;
        writer.write_event(Event::Text(BytesText::new(&atom.display.string)))?;
        writer.write_event(Event::End(BytesEnd::new("ChapterString")))?;

        writer.write_event(Event::Start(BytesStart::new("ChapterLanguage")))?;
        writer.write_event(Event::Text(BytesText::new(&atom.display.language)))?;
        writer.write_event(Event::End(BytesEnd::new("ChapterLanguage")))?;

        writer.write_event(Event::Start(BytesStart::new("ChapLanguageIETF")))?;
        writer.write_event(Event::Text(BytesText::new(&atom.display.language_ietf)))?;
        writer.write_event(Event::End(BytesEnd::new("ChapLanguageIETF")))?;

        writer.write_event(Event::End(BytesEnd::new("ChapterDisplay")))?;

        writer.write_event(Event::End(BytesEnd::new("ChapterAtom")))?;
    }

    // Close EditionEntry
    writer.write_event(Event::End(BytesEnd::new("EditionEntry")))?;

    // Close Chapters
    writer.write_event(Event::End(BytesEnd::new("Chapters")))?;

    Ok(writer.into_inner().into_inner())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_timestamp_parsing() {
        assert_eq!(parse_timestamp_ns("00:00:05.000000000"), 5_000_000_000);
        assert_eq!(parse_timestamp_ns("00:01:30.500000000"), 90_500_000_000);
        assert_eq!(parse_timestamp_ns("01:00:00.000000000"), 3_600_000_000_000);
    }

    #[test]
    fn test_timestamp_formatting() {
        assert_eq!(format_timestamp_ns(5_000_000_000), "00:00:05.000000000");
        assert_eq!(format_timestamp_ns(90_500_000_000), "00:01:30.500000000");
    }

    #[test]
    fn test_snap_previous() {
        let keyframes = vec![1_000_000_000, 5_000_000_000, 10_000_000_000];
        let threshold = 1_000_000_000; // 1 second

        // Snap to previous within threshold
        assert_eq!(
            find_snap_target(5_500_000_000, &keyframes, threshold, SnapMode::Previous),
            Some(5_000_000_000)
        );

        // Too far from previous
        assert_eq!(
            find_snap_target(7_000_000_000, &keyframes, threshold, SnapMode::Previous),
            None
        );
    }

    #[test]
    fn test_snap_nearest() {
        let keyframes = vec![1_000_000_000, 5_000_000_000, 10_000_000_000];
        let threshold = 2_000_000_000; // 2 seconds

        // Closer to 5s
        assert_eq!(
            find_snap_target(6_000_000_000, &keyframes, threshold, SnapMode::Nearest),
            Some(5_000_000_000)
        );

        // Closer to 10s
        assert_eq!(
            find_snap_target(9_000_000_000, &keyframes, threshold, SnapMode::Nearest),
            Some(10_000_000_000)
        );
    }
}
