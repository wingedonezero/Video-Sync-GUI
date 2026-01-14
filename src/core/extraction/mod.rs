//! Track and attachment extraction

pub mod tracks;
pub mod attachments;

pub use tracks::{TrackExtractor, parse_mkvmerge_json};
