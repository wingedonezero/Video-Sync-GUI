//! Subtitle processing module.
//!
//! Provides parsing, writing, and sync adjustment for subtitle files.
//!
//! # Architecture
//!
//! This module follows the same pattern as the `analysis` module:
//! - **Pure functions** in submodules for business logic
//! - **Pluggable strategies** for sync modes
//! - **Clean public API** via re-exports
//!
//! # Components
//!
//! - **types**: Core data structures (SubtitleData, Event, Style)
//! - **parsers**: Format-specific parsers (ASS, SRT)
//! - **writers**: Format-specific writers (ASS, SRT)
//! - **sync**: Sync mode implementations (time-based, video-verified)
//! - **frame_utils**: Video frame utilities (for video-verified mode)
//!
//! # Usage
//!
//! ```ignore
//! use vsg_core::subtitles::{
//!     parse_file, write_file, create_sync_mode,
//!     SyncModeType, SyncConfig, WriteOptions,
//! };
//!
//! // Parse a subtitle file
//! let mut data = parse_file("subtitles.ass")?;
//!
//! // Apply sync adjustment
//! let sync_mode = create_sync_mode(SyncModeType::TimeBased);
//! let config = SyncConfig::time_based(150.0, 50.0);
//! let result = sync_mode.apply(&mut data, &config)?;
//!
//! // Write output
//! write_file(&data, "output.ass", &WriteOptions::default())?;
//! ```

mod error;
pub mod frame_utils;
pub mod parsers;
pub mod sync;
mod types;
pub mod writers;

use std::fs;
use std::path::Path;

// Re-export core types
pub use types::{
    AssColor, RoundingMode, SubtitleData, SubtitleEvent, SubtitleFormat, SubtitleMetadata,
    SubtitleStyle, SyncEventData, WriteOptions,
};

// Re-export errors
pub use error::{FrameError, ParseError, SubtitleError, SyncError};

// Re-export parsers
pub use parsers::{parse_ass, parse_ass_time, parse_content, parse_srt, parse_srt_time};

// Re-export writers
pub use writers::{format_ass_time, format_srt_time, write_ass, write_content, write_srt};

// Re-export sync
pub use sync::{
    calculate_video_verified_offset, create_sync_mode, SyncConfig, SyncDetails, SyncMode,
    SyncModeType, SyncResult, VideoVerifiedCalcResult, VideoVerifiedConfig,
};

/// Parse a subtitle file from disk.
///
/// Auto-detects format from file extension and content.
///
/// # Arguments
/// * `path` - Path to the subtitle file.
///
/// # Returns
/// * `Ok(SubtitleData)` - Parsed subtitle data with source_path set.
/// * `Err(SubtitleError)` - If reading or parsing fails.
pub fn parse_file(path: impl AsRef<Path>) -> Result<SubtitleData, SubtitleError> {
    let path = path.as_ref();

    // Read file content
    let content =
        fs::read_to_string(path).map_err(|e| SubtitleError::read(path.to_path_buf(), e))?;

    // Detect format from extension, fall back to content detection
    let format = SubtitleFormat::from_extension(path);

    // Parse content
    let mut data = parse_content(&content, format)?;

    // Record source path
    data.source_path = Some(path.to_path_buf());

    Ok(data)
}

/// Write subtitle data to a file.
///
/// Uses the format from SubtitleData, or detects from file extension.
///
/// # Arguments
/// * `data` - Subtitle data to write.
/// * `path` - Output file path.
/// * `options` - Write options (rounding, etc.).
///
/// # Returns
/// * `Ok(())` - File written successfully.
/// * `Err(SubtitleError)` - If writing fails.
pub fn write_file(
    data: &SubtitleData,
    path: impl AsRef<Path>,
    options: &WriteOptions,
) -> Result<(), SubtitleError> {
    let path = path.as_ref();

    // Determine format from path extension or use data's format
    let format = SubtitleFormat::from_extension(path).unwrap_or(data.format);

    // Generate content
    let content = write_content(data, format, options);

    // Write to file
    fs::write(path, content).map_err(|e| SubtitleError::write(path.to_path_buf(), e))?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;
    use tempfile::NamedTempFile;

    #[test]
    fn test_parse_and_write_ass() {
        let content = r#"[Script Info]
Title: Test

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,20,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:04.00,Default,,0,0,0,,Hello, world!
"#;

        // Write to temp file
        let mut temp_file = NamedTempFile::with_suffix(".ass").unwrap();
        temp_file.write_all(content.as_bytes()).unwrap();

        // Parse
        let data = parse_file(temp_file.path()).unwrap();
        assert_eq!(data.events.len(), 1);
        assert!((data.events[0].start_ms - 1000.0).abs() < 10.0);

        // Write to another temp file
        let output_file = NamedTempFile::with_suffix(".ass").unwrap();
        write_file(&data, output_file.path(), &WriteOptions::default()).unwrap();

        // Re-parse and verify
        let reparsed = parse_file(output_file.path()).unwrap();
        assert_eq!(reparsed.events.len(), 1);
    }

    #[test]
    fn test_parse_and_write_srt() {
        let content = "1\n00:00:01,000 --> 00:00:04,000\nHello, world!\n";

        let mut temp_file = NamedTempFile::with_suffix(".srt").unwrap();
        temp_file.write_all(content.as_bytes()).unwrap();

        let data = parse_file(temp_file.path()).unwrap();
        assert_eq!(data.events.len(), 1);

        let output_file = NamedTempFile::with_suffix(".srt").unwrap();
        write_file(&data, output_file.path(), &WriteOptions::default()).unwrap();

        let reparsed = parse_file(output_file.path()).unwrap();
        assert_eq!(reparsed.events.len(), 1);
    }

    #[test]
    fn test_sync_workflow() {
        let mut data = SubtitleData::new();
        data.events
            .push(SubtitleEvent::new(1000.0, 4000.0, "Test"));

        let sync_mode = create_sync_mode(SyncModeType::TimeBased);
        let config = SyncConfig::time_based(500.0, 0.0);

        let result = sync_mode.apply(&mut data, &config).unwrap();

        assert_eq!(result.events_affected, 1);
        assert!((data.events[0].start_ms - 1500.0).abs() < 0.001);
    }
}
