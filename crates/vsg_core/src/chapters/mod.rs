//! Chapter handling module for Matroska files.
//!
//! This module provides functionality for working with Matroska chapter data:
//!
//! - **Extraction** (`extractor`): Extract chapters from MKV files using mkvextract
//! - **Parsing** (`parser`): Parse and serialize Matroska chapter XML format
//! - **Shifting** (`shifter`): Apply time offsets to chapter timestamps
//! - **Snapping** (`snapper`): Align chapters to video keyframes
//!
//! # Architecture
//!
//! The chapter pipeline typically follows this flow:
//!
//! 1. Extract chapters from source video using `extract_chapters()`
//! 2. Parse XML into `ChapterData` using `parse_chapter_xml()`
//! 3. Optionally shift timestamps using `shift_chapters()`
//! 4. Optionally snap to keyframes using `snap_chapters()`
//! 5. Serialize back to XML using `serialize_chapter_xml()`
//!
//! # Example
//!
//! ```ignore
//! use vsg_core::chapters::{
//!     extract_chapters_to_string, parse_chapter_xml, shift_chapters,
//!     snap_chapters, extract_keyframes, serialize_chapter_xml, SnapMode,
//! };
//! use std::path::Path;
//!
//! // Extract chapters from source
//! let xml = extract_chapters_to_string(Path::new("source.mkv"))?;
//! if let Some(xml) = xml {
//!     // Parse into structured data
//!     let mut chapters = parse_chapter_xml(&xml)?;
//!
//!     // Apply -500ms offset to sync with video
//!     shift_chapters(&mut chapters, -500);
//!
//!     // Snap to keyframes for better seeking
//!     let keyframes = extract_keyframes(Path::new("source.mkv"))?;
//!     snap_chapters(&mut chapters, &keyframes, SnapMode::Previous);
//!
//!     // Write back to file
//!     let output_xml = serialize_chapter_xml(&chapters);
//!     std::fs::write("chapters.xml", output_xml)?;
//! }
//! ```

mod extractor;
mod parser;
mod shifter;
mod snapper;
pub mod types;

// Re-export main types
pub use types::{
    format_timestamp_ns, parse_timestamp_ns, ChapterData, ChapterEntry, ChapterError,
    ChapterName, ChapterResult, KeyframeInfo,
};

// Re-export extraction functions
pub use extractor::{extract_chapters, extract_chapters_to_string, has_chapters};

// Re-export parsing functions
pub use parser::{
    parse_chapter_file, parse_chapter_xml, serialize_chapter_xml, write_chapter_file,
};

// Re-export shifting functions
pub use shifter::{
    max_negative_shift, shift_chapters, shift_chapters_copy, shift_chapters_strict,
};

// Re-export snapping functions
pub use snapper::{
    calculate_snap_stats, extract_keyframes, extract_keyframes_limited, snap_chapters,
    snap_chapters_copy, snap_chapters_with_threshold, SnapMode, SnapStats,
};
