//! Pipeline step implementations.
//!
//! Each step handles a specific phase of the sync/merge pipeline.

mod analyze;
mod attachments;
mod audio_correction;
mod chapters;
mod extract;
mod mux;
mod subtitles;

pub use analyze::AnalyzeStep;
pub use attachments::AttachmentsStep;
pub use audio_correction::AudioCorrectionStep;
pub use chapters::ChaptersStep;
pub use extract::ExtractStep;
pub use mux::MuxStep;
pub use subtitles::SubtitlesStep;
