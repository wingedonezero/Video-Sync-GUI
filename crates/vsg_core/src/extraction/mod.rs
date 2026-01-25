//! Media file extraction module.
//!
//! This module provides functionality for extracting information and content
//! from media files (primarily MKV):
//!
//! - **Container Info**: Read track timing information (container delays)
//! - **Track Extraction**: Extract audio, video, and subtitle tracks
//! - **Attachment Extraction**: Extract fonts and other attachments
//!
//! # Container Delays
//!
//! The container delay (also called `minimum_timestamp`) is the first
//! presentation timestamp of a track within the container. This is crucial
//! for preserving the original A/V sync of Source 1:
//!
//! ```text
//! Source 1 Video: delay = 100ms (defines output timeline)
//! Source 1 Audio: delay = 150ms
//! Relative Audio Delay: 150 - 100 = 50ms (preserves internal sync)
//! ```
//!
//! For synced sources (Source 2, Source 3), the correlation analysis already
//! accounts for container delays, so only the correlation result is used.
//!
//! # Usage
//!
//! ```ignore
//! use vsg_core::extraction::{read_container_info, extract_fonts};
//!
//! // Read container delays for delay calculation
//! let info = read_container_info("Source 1", Path::new("/path/to/source.mkv"))?;
//! let audio_delay = info.relative_audio_delay(1); // Track ID 1
//!
//! // Extract fonts for subtitle rendering
//! let fonts = extract_fonts("Source 1", Path::new("/path/to/source.mkv"), Path::new("/temp"))?;
//! ```

mod attachments;
mod container_info;
mod tracks;
mod types;

// Re-export public types
pub use types::{
    ContainerInfo,
    ExtractedAttachment,
    ExtractedTrack,
    ExtractRequest,
    ExtractionError,
    ExtractionOutput,
};

// Re-export public functions
pub use container_info::{read_all_container_info, read_container_info};
pub use tracks::{extract_single_track, extract_tracks};
pub use attachments::{extract_all_attachments, extract_fonts, list_attachments};
