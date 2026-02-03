//! Track and attachment extraction module.
//!
//! This module provides functionality for extracting data from Matroska files:
//!
//! - **Probing** (`probe`): Get file information using mkvmerge -J
//! - **Tracks** (`tracks`): Extract video, audio, and subtitle tracks
//! - **Attachments** (`attachments`): Extract fonts and other attachments
//! - **MkvExtract** (`mkvextract`): Low-level mkvextract command wrapper
//!
//! # Architecture
//!
//! The extraction pipeline typically follows this flow:
//!
//! 1. Probe the file with `probe_file()` to get track/attachment info
//! 2. Select tracks to extract based on type, language, etc.
//! 3. Extract tracks with `extract_tracks_batch()` or individual functions
//! 4. Extract attachments with `extract_all_attachments()` or filters
//!
//! # Example
//!
//! ```ignore
//! use vsg_core::extraction::{
//!     probe_file, extract_track_auto, extract_font_attachments, TrackType,
//! };
//! use std::path::Path;
//!
//! // Probe the file
//! let probe = probe_file(Path::new("source.mkv"))?;
//!
//! // Print track info
//! for track in &probe.tracks {
//!     println!("{}", track.summary());
//! }
//!
//! // Extract first video track
//! if let Some(video) = probe.default_video() {
//!     let extracted = extract_track_auto(
//!         Path::new("source.mkv"),
//!         video.id,
//!         Path::new("/tmp/extract"),
//!         "video",
//!     )?;
//!     println!("Video extracted to: {}", extracted.output_path.display());
//! }
//!
//! // Extract fonts for subtitle rendering
//! let fonts = extract_font_attachments(
//!     Path::new("source.mkv"),
//!     Path::new("/tmp/fonts"),
//! )?;
//! println!("Extracted {} fonts", fonts.files.len());
//! ```

mod attachments;
mod mkvextract;
mod probe;
mod tracks;
pub mod types;

// Re-export types
pub use types::{
    AttachmentInfo, ExtractedAttachments, ExtractedTrack, ExtractionError, ExtractionResult,
    ProbeResult, TrackInfo, TrackProperties, TrackType,
};

// Re-export probe functions
pub use probe::{
    build_track_description, count_tracks_by_type, friendly_codec_name, get_attachments,
    get_detailed_stream_info, get_duration_secs, get_tracks, is_matroska, probe_file,
    FfprobeStreamInfo,
};

// Re-export track extraction functions
pub use tracks::{
    build_track_output_path, extract_all_of_type, extract_by_language, extract_track_auto,
    extract_track_smart, extract_tracks_batch, get_audio_tracks_sorted, get_reference_video_track,
    verify_extraction_result, ExtractionMethod, SmartExtractResult, TrackExtractSpec,
};

// Re-export attachment extraction functions
pub use attachments::{
    extract_all_attachments, extract_attachments_by_id, extract_font_attachments, has_attachments,
    has_font_attachments, list_attachments, total_attachment_size,
};

// Re-export low-level mkvextract functions
pub use mkvextract::{
    extension_for_codec, extract_attachments, extract_audio_with_ffmpeg, extract_chapters_xml,
    extract_cues, extract_tags, extract_timestamps, extract_track, extract_tracks,
    pcm_codec_from_bit_depth, requires_ffmpeg_extraction,
};
