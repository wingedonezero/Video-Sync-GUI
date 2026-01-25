//! Chapter processing module.
//!
//! This module handles extraction, modification, and serialization of
//! Matroska chapters.
//!
//! # Features
//!
//! - **Extraction**: Read chapters from MKV files via mkvextract
//! - **Shifting**: Apply global sync offset to chapter timestamps
//! - **Normalization**: Fix end times, remove duplicates
//! - **Renaming**: Sequential chapter names ("Chapter 01", etc.)
//! - **Serialization**: Write chapters back to Matroska XML format
//!
//! # Usage
//!
//! ```ignore
//! use vsg_core::chapters::{extract_chapters, process_chapters, write_chapters_xml};
//!
//! // Extract chapters from source file
//! let mut chapters = extract_chapters(Path::new("/path/to/source.mkv"))?;
//!
//! // Process with shift and normalization
//! let config = ChapterProcessConfig::default();
//! let log = process_chapters(&mut chapters, 500, &config); // +500ms shift
//!
//! // Write to output file
//! write_chapters_xml(&chapters, Path::new("/temp/chapters.xml"))?;
//! ```

mod extract;
mod process;
mod types;

// Re-export types
pub use types::{
    Chapter, ChapterDisplay, ChapterError, ChapterLanguage, ChapterList,
    format_timestamp, format_timestamp_readable, parse_timestamp,
};

// Re-export functions
pub use extract::{extract_chapters, parse_chapter_xml};
pub use process::{
    process_chapters, write_chapters_xml, ChapterProcessConfig,
};
