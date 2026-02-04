//! Subtitle writers for various formats.
//!
//! Each writer is a pure function that takes SubtitleData and returns a formatted string.

mod ass;
mod srt;

pub use ass::{format_ass_time, write_ass};
pub use srt::{format_srt_time, write_srt};

use crate::subtitles::types::{SubtitleData, SubtitleFormat, WriteOptions};

/// Write subtitle data to string in the specified format.
pub fn write_content(data: &SubtitleData, format: SubtitleFormat, options: &WriteOptions) -> String {
    match format {
        SubtitleFormat::Ass => write_ass(data, options),
        SubtitleFormat::Srt | SubtitleFormat::WebVtt => write_srt(data, options),
    }
}
